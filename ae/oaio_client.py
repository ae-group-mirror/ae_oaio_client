""" Our Asynchronously Interchangeable Objects Client

"""
import os
import shutil

from ast import literal_eval
from typing import Optional, Sequence

import requests

from ae.base import (                                                                                   # type: ignore
    app_name_guess, os_host_name, os_path_isdir, os_path_isfile, os_path_join, os_path_relpath,
    os_user_name, read_file, write_file,
    ErrorMsgMixin)
from ae.cloud_storage import CshApiBase, csh_api_class                                                  # type: ignore
from ae.oaio_model import (                                                                             # type: ignore
    CREATE_WRITE_ACCESS, DELETE_ACTION, FILES_DIR, FILES_VALUES_KEY, MAX_STAMP_DIFF, OBJECTS_DIR,
    READ_ONLY_ACCESS, REGISTER_ACTION, ROOT_VALUES_KEY, UPLOAD_ACTION,
    OaioCshIdType, OaioMapType, OaioIdType, OaioStampType, OaioValuesType, OaioCshWriteAccessType,
    OaiObject, extra_headers, now_stamp, object_dict, object_id, stamp_diff)
from ae.paths import Collector, normalize, placeholder_path                                             # type: ignore


__version__ = '0.3.5'


LAST_SYNC_STAMP_FILE = 'last_sync_stamp.txt'
OLDEST_SYNC_STAMP = '20221231111111111111'


class OaioClient(ErrorMsgMixin):
    """ interface to manage creations, updates and deletions of oaio objects of a user.

    .. note:: after creating an instance the :meth:`.synchronize` method has to be called at least once.

    """
    def __init__(self, host: str, credentials: dict[str, str],
                 app_id: str = "",
                 device_id: str = "",
                 csh_default_id: OaioCshIdType = 'Digi',
                 auto_sync_sec: float = 360.9,
                 client_root: str = "{ado}/oaio_root/",
                 ):
        """ initialize a new client instance to connect to the oaio server.

        :param host:            oaio server host name/address and optional port number.
        :param credentials:     oaio server user identification credentials kwargs (dict with the keys
                                'username' and 'password').
        :param app_id:          optional id/name of the app from where the client is connecting from.
                                defaults to :func:`~ae.base.app_name_guess`.
        :param device_id:       id of the client device.
                                defaults to :func:`~ae.base.os_host_name`.
        :param auto_sync_sec:   time in seconds to sync with oaio server on every object registering or update.
                                defaults to 260 seconds. pass zero/0 in order to disable auto synchronization.
        :param client_root:     path to the folder on the local device where the oaio info and files gets cached.
                                defaults to the placeholder path "{ado}/oaio_root/".
        :param csh_default_id:  id for the default cloud storage server to use.
                                defaults to 'Digi'.
        """
        self.base_url = 'http' + ('' if host[:9] in ('localhost', '127.0.0.1') else 's') + f'://{host}/api/'
        self.credentials = credentials
        self.user_name = credentials.get('username') or os_user_name()
        self.app_id = app_id or app_name_guess()
        self.device_id = device_id or os_host_name()
        self.auto_sync_seconds = auto_sync_sec
        self.client_root = normalize(client_root)
        self.csh_default_id = csh_default_id

        self.session = requests.Session()
        self.session.headers.update(extra_headers(self.user_name, self.device_id, self.app_id))
        self.connected = False

        self._init_client_folders()
        self._last_sync_stamp = ""
        self.client_objectz: OaioMapType = {}
        self.synchronize_with_server_if_online()

    def __del__(self):
        """ automatic logout and close of the http session. """
        if self.connected:
            self._request('post', 'logout/')
        if self.session:
            self.session.close()

    def _auto_sync_check(self):
        """ check if synchronization with servers should be done. """
        if self.auto_sync_seconds and stamp_diff(self.last_sync_stamp, now_stamp()) > self.auto_sync_seconds:
            self.synchronize_with_server_if_online()

    def _csh_api(self, csh_id: OaioCshIdType) -> Optional[CshApiBase]:
        """ determine api and credentials of cloud storage host specified by its id from the web server db/config. """
        res = self._request('get', f'csh_args/{csh_id}')
        if res and res.ok:
            csh_kwargs = res.json()
            api_class = csh_api_class(csh_id)
            return api_class(**csh_kwargs)

        self.error_message = f"oaio server {getattr(res, 'status_code', 'offline')} error in {csh_id}-args fetch"
        return None

    def _client_file_root(self, oaio_id: OaioIdType, values: OaioValuesType) -> str:
        """ determine the path on client/device where the file(s) attached to an oaio get stored.

        :param oaio_id:         id of the oaio.
        :param values:          oaio values (client_values if upload else server_values).
        :return:                path string.
        """
        if ROOT_VALUES_KEY not in values:
            root_folder = os_path_join(self.client_root, FILES_DIR, oaio_id)
        else:
            root_folder = values[ROOT_VALUES_KEY]   # use values root_folder if isabs or starts with PATH_PLACEHOLDER
            if root_folder and root_folder[0] == '{':
                root_folder = normalize(root_folder)
            else:   # if not os.path.isabs(root_folder):
                root_folder = os_path_join(self.client_root, root_folder)
        return root_folder

    def _download_object(self, oai_obj: OaiObject) -> bool:
        """ save oaio info and download optional attached files to local device/cache.

        :param oai_obj:         :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :return:                True if object info and files got downloaded without errors, else False.
        """
        files, csh_api, client_path, server_path = self._object_client_server_file_paths(oai_obj, upload=False)
        if files and csh_api is None:
            return False

        for file_path in files:
            assert csh_api is not None  # for mypy
            content = csh_api.deployed_file_content(os_path_join(server_path, file_path))
            if content is None:
                self.error_message = f"cloud storage download of ({oai_obj}.){file_path} error: {csh_api.error_message}"
                return False
            write_file(os_path_join(client_path, file_path), content)

        self._save_client_object_info(oai_obj)

        return True

    def _folder_files(self, folder_path: str) -> Sequence[str]:
        """ collect all files under the specified root folder.

        :param folder_path:     root folder to collect files from (can contain path placeholders).
        :return:                list of file names (relative to the root/folder_path and without any path placeholders).
        """
        coll = Collector(main_app_name=self.app_id)
        coll.collect(folder_path, append=("**/*", "**/.*"), only_first_of=())
        return [os_path_relpath(_, folder_path) for _ in coll.files]

    def _init_client_folders(self):
        """ called on the first start of the client to create the folders and files under :attr:`.client_root`. """
        file_path = os_path_join(self.client_root, OBJECTS_DIR)
        if not os_path_isdir(file_path):
            os.makedirs(file_path)

        file_path = os_path_join(self.client_root, FILES_DIR)
        if not os_path_isdir(file_path):
            os.makedirs(file_path)

        file_path = os_path_join(self.client_root, LAST_SYNC_STAMP_FILE)        # add file with old self.last_sync_stamp
        if not os_path_isfile(file_path):                                       # to ensure sync on first app start
            write_file(file_path, OLDEST_SYNC_STAMP)                            # (difference > self.auto_sync_seconds)

    def _load_client_object_info(self, oaio_id: OaioIdType, info_path: str = "") -> OaiObject:
        """ load actual client/local oaio info of the oaio specified by its id. """
        obj_lit = read_file(os_path_join(info_path or os_path_join(self.client_root, OBJECTS_DIR), oaio_id))
        obj_dict = literal_eval(obj_lit)
        return OaiObject(**obj_dict)

    def _load_client_objectz(self) -> OaioMapType:
        """ load actual client/local oaio infos of all local oai objects.

        :return:                mapping object with objectz stored on the local device.
        """
        objectz = {}
        info_path = os_path_join(self.client_root, OBJECTS_DIR)
        for oaio_id in os.listdir(info_path):
            oai_obj = self._load_client_object_info(oaio_id, info_path=info_path)
            objectz[oaio_id] = oai_obj
        return objectz

    def _load_server_objectz(self) -> OaioMapType:
        """ get from server all newly added and changed objectz of all the subscriptions of the current user.

        :return:                mapping object with objectz subscribed by the user from oaio server.
                                if the client is offline an empty mapping object.
        """
        objectz = {}
        res = self._request('get', 'oaio_stampz/')
        if res and res.ok:
            for oaio_dict in res.json():
                oai_obj = OaiObject(**oaio_dict)
                objectz[oai_obj.oaio_id] = oai_obj

        return objectz

    def _object_client_server_file_paths(self, oai_obj: OaiObject, upload: bool
                                         ) -> tuple[list[str], Optional[CshApiBase], str, str]:
        """ get attached files, the cloud storage api id, and the files root paths on client and cloud storage host. """
        oaio_id = oai_obj.oaio_id

        stamp = oai_obj.client_stamp if upload else oai_obj.server_stamp
        new_values = oai_obj.client_values if upload else oai_obj.server_values
        # _old_values = oai_obj.server_values if upload else self.client_objectz[oaio_id].values

        files = new_values.get(FILES_VALUES_KEY, [])
        csh_id = oai_obj.csh_id
        if not files or not csh_id or (csh_api := self._csh_api(csh_id)) is None:
            if files:
                self.error_message = f"wrong cloud storage '{csh_id}' for {'up' if upload else 'down'}load of {oai_obj}"
            return [], None, "", ""

        client_path = self._client_file_root(oaio_id, new_values)
        server_path = os_path_join(oaio_id, stamp)

        return files, csh_api, client_path, server_path

    def _reconnect_check(self) -> bool:
        """ check if server got already connected and (re)connect if not.

        :return                 True if still connected or successfully reconnected
                                or False if offline, connection cannot be established, CSRF token not available or
                                on any other server login failure/error; check the error in :attr:`.error_message`.
        """
        if self.connected:
            res = self._request('get', 'current_stamp/', _in_chk=True)
            if res and res.ok:
                client_stamp = now_stamp()
                server_stamp = res.json().get('current_stamp')
                if abs(stamp_diff(client_stamp, server_stamp)) > MAX_STAMP_DIFF:
                    self.error_message = f"clocks are out of sync; client={client_stamp} server={server_stamp}"
                    return False
                return server_stamp

            self.session.headers.pop('X-CSRFToken')
            self.connected = False

        if not self.connected:
            res = self._request('post', 'login/', _in_chk=True,
                                json=self.credentials, headers={'Content-Type': 'application/json'})
            if not res or not res.ok:
                self.error_message = f"user '{self.user_name}' authentication error {getattr(res, 'status_code', '')}"
                return False
            self.connected = True

        return True

    def _request(self, method: str, slug: str, _in_chk: bool = False, **request_kwargs
                 ) -> Optional[requests.Response]:
        """ oaio server request checking CSRF for POST and automatic reconnect.

        :param method:          http request method (either 'get' or 'post').
        :param slug:            request slug added to base URL.
        :param _in_chk:         preventing endless recursion. only True for internal calls from
                                :meth:`~OaioClient._reconnect_check`, else False.
        :param request_kwargs:  extra kwargs passed onto the http request :paramref:`~_request.method` call.
        :return:                http response, or None if connection cannot be established (offline, authentication, ..)
                                or if any other error occurred (check self.error_message for details).
        """
        url = self.base_url + slug
        try:
            if not _in_chk and not self._reconnect_check():
                return None

            hdr_token = self.session.headers.get('X-CSRFToken')     # only DELETE|PATCH|POST|PUT|... need a CSRF token
            ses_token = self.session.cookies.get('csrftoken')
            if method != 'get' and (not hdr_token or hdr_token != ses_token):
                if not hdr_token:  # works without this if (same: if hdr_token == ses_token), but with 10% more traffic?
                    res = self.session.get(url)                     # fetch new/changed CSRF token from oaio server
                    ses_token = self.session.cookies.get('csrftoken')
                    if not res or not res.ok or not ses_token:
                        raise Exception(f"CSRF fetch error {getattr(res, 'status_code', '?')}; tok={bool(ses_token)}")
                request_kwargs.setdefault('cookies', {'csrftoken': ses_token})
                self.session.headers['X-CSRFToken'] = ses_token
                self.session.headers['Referer'] = url               # needed only for https requests

            met = getattr(self.session, method)
            res = met(url, **request_kwargs)
            res.raise_for_status()
            self.error_message = ""
            return res

        except (requests.HTTPError, requests.ConnectionError, Exception) as exc:
            if 'json' in request_kwargs and 'password' in request_kwargs['json']:   # hide password if in request_kwargs
                request_kwargs['json']['password'] = request_kwargs['json']['password'][:2] + "*" * 9
            self.error_message = f"{method}-request err '{exc}'; URL='{url}' CHK={_in_chk} kw={request_kwargs}"

        return None

    def _save_client_object_info(self, oai_obj: OaiObject):
        """ save oaio to local oaio info. """
        if not oai_obj.client_stamp:    # just downloaded from server
            oai_obj.client_stamp = oai_obj.server_stamp
            oai_obj.client_values = oai_obj.server_values

        self.client_objectz[oai_obj.oaio_id] = oai_obj
        write_file(os_path_join(self.client_root, OBJECTS_DIR, oai_obj.oaio_id), repr(object_dict(oai_obj)))

    def _upload_object(self, oai_obj: OaiObject, register: bool = False) -> bool:
        """ save local/client object and try to send changes to storage and oaio/web servers.

        :param oai_obj:         :class:`~ae.oaio_model.OaiObject` dataclass instance to update/upload/register.
        :param register:        pass True for new oaio to register or False for already existing ones to be updated.
        :return:                True if register/upload went well or False on failure or if servers are offline.
        """
        self._save_client_object_info(oai_obj)

        files, csh_api, client_path, server_path = self._object_client_server_file_paths(oai_obj, upload=True)
        if files and csh_api is None:
            return False

        for file_path in files:
            assert csh_api is not None  # for mypy
            if not csh_api.deploy_file(os_path_join(server_path, file_path),
                                       source_path=os_path_join(client_path, file_path)):
                self.error_message = f"'{file_path}' cloud storage upload error: '{csh_api.error_message}' of {oai_obj}"
                return False

        action = REGISTER_ACTION if register else UPLOAD_ACTION
        res = self._request('post', f'{action}/', json=object_dict(oai_obj))
        if not res:
            self.error_message = f"object upload of {oai_obj} to server postponed."
            return False
        srv_dict = res.json()
        if 'e_r_r' in srv_dict:
            self.error_message = f"_upload_object() received server error: {srv_dict['e_r_r']}"
            return False
        assert srv_dict.get('oaio_id') == oai_obj.oaio_id

        for field_name, value in srv_dict.items():
            setattr(oai_obj, field_name, value)   # update field values client_stamp, server_stamp, ...
        self._save_client_object_info(oai_obj)

        return True

    # public api of this client instance ##########################################################

    @property
    def last_sync_stamp(self) -> OaioStampType:
        """ timestamp of last synchronization with the oaio/storage servers.

        :getter:                timestamp of the last server synchronization.
        :setter:                any assigned error message will be accumulated to recent error messages.
                                pass an empty string to reset the error message.
        """
        if not self._last_sync_stamp:
            self._last_sync_stamp = read_file(os_path_join(self.client_root, LAST_SYNC_STAMP_FILE))
        return self._last_sync_stamp

    @last_sync_stamp.setter
    def last_sync_stamp(self, stamp: OaioStampType):
        write_file(os_path_join(self.client_root, LAST_SYNC_STAMP_FILE), stamp)
        self._last_sync_stamp = stamp

    def register_file(self, file_name: str, root_path: str = "", stamp: OaioStampType = "", csh_id: OaioCshIdType = ""
                      ) -> Optional[OaiObject]:
        """ register new oaio file object.

        :param file_name:       name of the new file object to register.
        :param root_path:       root path on local-machine of the new file object to register.
                                using :attr:`.client_root` if not specified.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param csh_id:          cloud storage server id or empty string to use default cloud storage server.
        :return:                new OaiObject instance
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        :raises AssertionError: if file to register does not exist.
        """
        new_val = {FILES_VALUES_KEY: [file_name]}
        if root_path:
            new_val[ROOT_VALUES_KEY] = placeholder_path(root_path)
        file_path = normalize(os_path_join(root_path, file_name))
        assert os_path_isfile(file_path), f"file to register not found; {file_path}"
        return self.register_object(new_val, stamp=stamp, csh_id=csh_id)

    def register_folder(self, folder_path: str = "", stamp: OaioStampType = "",
                        csh_id: OaioCshIdType = "") -> Optional[OaiObject]:
        """ register new oaio folder object.

        :param folder_path:     root path on the local-machine/client of the new folder object to register.
                                using :attr:`.client_root` if not specified.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param csh_id:          cloud storage server id or empty string to use default cloud storage server.
        :return:                new OaiObject instance
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        :raises AssertionError: if files to register does not exist.
        """
        new_val = {FILES_VALUES_KEY: self._folder_files(folder_path)}
        if folder_path:
            new_val[ROOT_VALUES_KEY] = placeholder_path(folder_path)
        return self.register_object(new_val, stamp=stamp, csh_id=csh_id)

    def register_object(self, values: OaioValuesType, stamp: OaioStampType = "", csh_id: OaioCshIdType = ""
                        ) -> Optional[OaiObject]:
        """ register new oaio data object.

        :param values:          values data to register as a new oaio object.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param csh_id:          cloud storage server id. using default cloud storage server if not specified or empty.
        :return:                new OaiObject instance.
        """
        stamp = stamp or now_stamp()

        oaio_id = object_id(user_name=self.user_name, device_id=self.device_id, app_id=self.app_id,
                            stamp=stamp, values=values)

        oai_obj = OaiObject(
            oaio_id=oaio_id,
            csh_id=csh_id or self.csh_default_id,
            client_stamp=stamp,                     # could be changed by server on upload if conflicts with other stamp
            client_values=values,
            csh_write_access=CREATE_WRITE_ACCESS,   # registering owner has always all access rights
        )

        if self._upload_object(oai_obj, register=True):
            self._auto_sync_check()

        return oai_obj

    def synchronize_with_server_if_online(self) -> bool:
        """ synchronize local changes to server and any update/changes done on other clients from server to this client.

        .. hint:: if not connected to the oaio server then this method tries first to (re-)connect.

        :return:                False if the client is offline or on sync error, else True.
        """
        if not self._reconnect_check():
            return False

        soz = self._load_server_objectz()
        self.client_objectz = coz = self._load_client_objectz()
        error = False

        for cob in sorted(coz.values(), key=lambda _: _.client_stamp):
            if cob.client_stamp > cob.server_stamp:
                error = not self._upload_object(cob) or error   # self._upload_object() put self.error_message on error

        newer = [_ for _ in soz.values() if coz.get(_.oaio_id, OaiObject(_.oaio_id)).client_stamp < _.server_stamp]
        for sob in sorted(newer, key=lambda _: _.server_stamp):
            error = not self._download_object(sob) or error

        if not error:
            self.last_sync_stamp = now_stamp()

        return not error

    def unsubscribe(self, oaio_id: OaioIdType, user_name: str) -> str:
        """ remove subscription of an oai object for a user.

        :param oaio_id:         id of the oaio to unsubscribe.
        :param user_name:       subscribing user.
        :return:                empty string if subscription could be removed without error, else error message.
        """
        data = dict(POid=oaio_id, PUid=user_name)
        res = self._request('post', 'unsubscribe/', json=data)
        if not res or not res.ok:
            self.error_message = f"unsubscribe of {user_name}/'{oaio_id}' with {getattr(res, 'status_code', 'error')}"
        return self.error_message

    def update_file(self, oaio_id: OaioIdType, file_name: str = "", root_path: str = "") -> OaiObject:
        """ update oai file object locally.

        :param oaio_id:         id of the oai file object to update.
        :param file_name:       name of the file.
        :param root_path:       root path on local-machine of the new file object to register.
                                using :attr:`.client_root` if not specified.
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :raises AssertionError: if file to update does not exist.
        """
        values = self.client_objectz[oaio_id].client_values
        if file_name:
            values[FILES_VALUES_KEY] = file_name
        else:
            file_name = values[FILES_VALUES_KEY][0]
        if root_path:
            values[ROOT_VALUES_KEY] = root_path
        else:
            root_path = values.get(ROOT_VALUES_KEY, "")

        file_path = normalize(os_path_join(root_path, file_name))
        assert os_path_isfile(file_path), f"updated file {file_path} does not exist"

        return self.update_object(oaio_id, values)

    def update_folder(self, oaio_id: OaioIdType) -> OaiObject:
        """ update oai folder object locally.

        :param oaio_id:         id of the oai folder object to update.
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :raises AssertionError: if same file is in add_files and in removed_files,
                                or if one of the files to update does not exist.
        """
        values = self.client_objectz[oaio_id].client_values
        client_root = self._client_file_root(oaio_id, values)
        new_files = self._folder_files(client_root)
        values[FILES_VALUES_KEY] = new_files

        return self.update_object(oaio_id, values)

    def update_object(self, oaio_id: OaioIdType, values: OaioValuesType, stamp: OaioStampType = "") -> OaiObject:
        """ update oaio data object locally.

        :param oaio_id:         id of the oaio to update.
        :param values:          values of the oaio.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        """
        cob = self.client_objectz[oaio_id]

        cob.client_stamp = stamp or now_stamp()
        cob.client_values = values

        if self._upload_object(cob):   # save client changes locally and try to upload directly if client is online
            self._auto_sync_check()

        return cob

    def upsert_subscription(self, oaio_id: OaioIdType, user_name: str,
                            write_access: OaioCshWriteAccessType = READ_ONLY_ACCESS) -> int:
        """ add new subscriber of an oai object or update extra fields/defaults of an existing user subscription.

        :param oaio_id:         id of the oaio to subscribe to.
        :param user_name:       subscribing user.
        :param write_access:    user access rights to the subscribed oaio. pass e.g. the value
                                :data:`~ae.oaio_model.UPDATE_WRITE_ACCESS` to give the user update rights.
                                see allowed argument values in the :data:`~ae.oaio_model.ACCESS_RIGHTS` tuple.
        :return:                the primary key integer value (Pubz.Pid) of the added/updated Pubz subscription record
                                or 0/zero if an error occurred.
        """
        data = dict(POid=oaio_id, PUid=user_name, write_access=write_access)
        res = self._request('post', 'subscribe/', json=data)
        if not res or not res.ok:
            self.error_message = f"subscription of user {user_name} for object '{oaio_id}' failed"
            return 0
        return res.json().get('Pid', 0)

    def unregister_object(self, oaio_id: OaioIdType, wipe_files: bool = False):
        """ unregister/delete oai object.

        :param oaio_id:         id of the oaio to unregister.
        :param wipe_files:      pass True to also remove/wipe all attached file(s) on the local machine.
        """
        oai_obj = self.client_objectz.pop(oaio_id, None)
        if oai_obj is None:
            self.error_message = f"client object to delete/unregister with id '{oaio_id}' not found"
            return False

        # noinspection PyTypeChecker
        res = self._request('post', f'{DELETE_ACTION}/', json=object_dict(oai_obj))             # PyCharm inspection Bug
        if not res or not res.ok:
            self.error_message = f"object delete/unregister of {oai_obj} to server failed."
            return False

        if os_path_isfile(path := os_path_join(self.client_root, OBJECTS_DIR, oaio_id)):
            os.remove(path)

        if wipe_files:
            # noinspection PyUnresolvedReferences
            if os_path_isdir(path := self._client_file_root(oaio_id, oai_obj.client_values)):   # PyCharm inspection Bug
                shutil.rmtree(path)

        self._auto_sync_check()

        return True
