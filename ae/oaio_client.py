""" Our Asynchronously Interchangeable Objects Client

"""
import dataclasses
import os
import shutil

from ast import literal_eval
from typing import Optional, Sequence

import requests

from ae.base import app_name_guess, os_host_name, ErrorMsgMixin, os_user_name, read_file, write_file    # type: ignore
from ae.cdnz import CdnApiBase, cdn_api_class                                                           # type: ignore
from ae.paths import Collector, normalize, placeholder_path                                             # type: ignore
from ae.oaio_model import (  # type: ignore
    CREATE_WRITE_ACCESS, DELETE_ACTION, FILES_DIR, FILES_VALUES_KEY, MAX_STAMP_DIFF, OBJECTS_DIR,
    READ_ONLY_ACCESS, REGISTER_ACTION, ROOT_VALUES_KEY, UPLOAD_ACTION,
    OaioCdnIdType, OaioMapType, OaioIdType, OaioStampType, OaioValuesType, OaioCdnWriteAccessType,
    extra_headers, now_stamp, object_dict, object_id, stamp_diff, OaiObject,
)


__version__ = '0.3.1'


class OaioClient(ErrorMsgMixin):
    """ interface to manage creations, updates and deletions of oaio objects of a user.

    .. note:: after creating an instance the :meth:`.synchronize` method has to be called at least once.

    """
    def __init__(self, host: str, credentials: dict[str, str],
                 app_id: str = "",
                 device_id: str = "",
                 cdn_default_id: OaioCdnIdType = 'Digi',
                 local_objectz: Optional[OaioMapType] = None,
                 local_root_path: str = "{ado}/oaio_root/",
                 auto_sync_sec: float = 360.9,
                 ):
        """ initialize a new client instance to connect to the oaio server.

        :param host:            oaio server host name/address and optional port number.
        :param credentials:     oaio server user identification credentials kwargs (dict with the keys
                                'username' and 'password').
        :param app_id:          optional id/name of the app from where the client is connecting from.
                                defaults to :func:`~ae.base.app_name_guess`.
        :param device_id:       id of the client device.
                                defaults to :func:`~ae.base.os_host_name`.
        :param cdn_default_id:  id for the default content server to use.
                                defaults to 'Digi'.
        :param local_objectz:   optional EMPTY mapping/dict-like object to map all the registered.
                                and subscribed oaio objects of a client.
        :param local_root_path: local path to the folder where the oaio info and files gets cached.
                                defaults to the placeholder path "{ado}/oaio_root/".
        :param auto_sync_sec:   time in seconds to sync with oaio server on every object registering or update.
        """
        self.base_url = f'https://{host}/api/'
        self.credentials = credentials
        self.user_name = credentials.get('username') or os_user_name()
        self.app_id = app_id or app_name_guess()
        self.device_id = device_id or os_host_name()
        self.cdn_default_id = cdn_default_id
        self.local_objectz = {} if local_objectz is None else local_objectz
        self.local_root_path = normalize(local_root_path)
        self.auto_sync_seconds = auto_sync_sec

        self.unsync_objectz: list[OaiObject] = []
        self.last_sync_stamp = ""
        self._init_root_path()
        self._load_local_object_infos()

        self.session = requests.Session()
        self.session.headers.update(extra_headers(self.user_name, self.device_id, self.app_id))
        self.connected = False
        self.synchronize_with_server_if_online()

    def __del__(self):
        if self.connected:
            self._request('post', 'logout/')
        if self.session:
            self.session.close()

    def _cdn_api(self, cdn_id: OaioCdnIdType) -> Optional[CdnApiBase]:
        """ determine the api and credentials of the CDN server specified by its id from the web server db/config. """
        res = self._request('get', f'cdn_credential/{cdn_id}/')
        if res:
            cdn_kwargs = res.json()
            api_class = cdn_api_class(cdn_id)
            return api_class(**cdn_kwargs)
        self.error_message = "oaio server is offline"
        return None

    def _changed_server_objectz(self) -> OaioMapType:
        """ get from server all newly added and changed objectz of all the subscriptions of the current user.

        :return:                mapping object with objectz from oaio server if online else an empty mapping object.
        """
        changed_objects = {}

        res = self._request('get', 'oaio_stampz/')
        if res and res.ok:
            for oaio_dict in res.json():
                oai_obj = OaiObject(**oaio_dict)

                oaio_id = oai_obj.oaio_id
                if oaio_id not in self.local_objectz:
                    changed_objects[oaio_id] = oai_obj
                elif oai_obj.server_stamp > self.local_objectz[oaio_id].client_stamp:
                    changed_objects[oaio_id] = oai_obj

        return changed_objects

    def _download_object(self, oai_obj: OaiObject) -> bool:
        """ save oaio info and download optional attached files to local device/cache.

        :param oai_obj:
        :return:                True if object info and files got downloaded without errors, else False.
        """
        files, cdn_api, client_path, server_path = self._object_client_server_file_paths(oai_obj)
        if cdn_api is None:
            return False

        for file_path in files:
            content = cdn_api.deployed_file_content(os.path.join(server_path, file_path))
            if content is None:
                self.error_message = f"CDN download of ({oai_obj}.){file_path} failed with: {cdn_api.error_message}"
                return False
            write_file(os.path.join(client_path, file_path), content)

        self._save_local_object_info(oai_obj)

        return True

    def _folder_files(self, folder_path: str) -> Sequence[str]:
        """ collect all files under the specified root folder.

        :param folder_path:     root folder to collect files from (can contain path placeholders).
        :return:                list of file names (with path placeholders).
        """
        coll = Collector(main_app_name=self.app_id)
        coll.collect(folder_path, append=("**/*", "**/.*"), only_first_of=())
        return [placeholder_path(file_path) for file_path in coll.files]

    def _init_root_path(self):
        """ called on the first start of the client to create the default folders under :attr:`.local_root_path`. """
        file_path = os.path.join(self.local_root_path, OBJECTS_DIR)
        if not os.path.isdir(file_path):
            os.makedirs(file_path)

        file_path = os.path.join(self.local_root_path, FILES_DIR)
        if not os.path.isdir(file_path):
            os.makedirs(file_path)

    def _load_local_object_infos(self):
        """ load actual client/local oaio info. """
        unsync = []
        self.local_objectz.clear()  # wipe content keeping mapping (maybe passed from app to notify/update UI on change)

        info_path = os.path.join(self.local_root_path, OBJECTS_DIR)
        for oaio_id in os.listdir(info_path):
            obj_lit = read_file(os.path.join(info_path, oaio_id))
            obj_dict = literal_eval(obj_lit)
            oai_obj = OaiObject(**obj_dict)

            if oai_obj.client_stamp != oai_obj.server_stamp:
                unsync.append(oai_obj)

            self.local_objectz[oaio_id] = oai_obj

        unsync.sort(key=lambda _obj: _obj.client_stamp)
        self.unsync_objectz = unsync

    def _object_client_server_file_paths(self, oai_obj: OaiObject) -> tuple[list[str], Optional[CdnApiBase], str, str]:
        """ get list of optionally attached files, the CDN api id and the files root paths on client and CDN server. """
        files = oai_obj.client_values.get(FILES_VALUES_KEY, [])
        cdn_api = None
        if not files or (cdn_api := self._cdn_api(oai_obj.cdn_id)) is None:
            if cdn_api is None:
                self.error_message = f"invalid CDN api; up/download of oaio ({oai_obj} failed"
            return [], None, "", ""

        oaio_id = oai_obj.oaio_id
        client_path = oai_obj.client_values.get(ROOT_VALUES_KEY)
        if client_path is None:
            client_path = os.path.join(self.local_root_path, FILES_DIR, oaio_id)
        server_path = os.path.join(oaio_id, oai_obj.client_stamp)

        return files, cdn_api, normalize(client_path), server_path

    def _reconnect_check(self) -> bool:
        """ check if server got already connected and (re)connect if not.

        :return                 True if still connected or successfully reconnected
                                or False if offline, connection cannot be established, CSRF token not available or
                                on any other server login failure/error; check the error in :attr:`.error_message`.
        """
        if self.connected:
            res = self._request('get', 'current_stamp/')
            if res and res.ok:
                client_stamp = now_stamp()
                server_stamp = res.json().get('current_stamp')
                if abs(stamp_diff(client_stamp, server_stamp)) > MAX_STAMP_DIFF:
                    self.error_message = f"clocks are out of sync; client={client_stamp} server={server_stamp}"
                    return False
                return server_stamp

            self.connected = False

        if not self.connected:
            res = self._request('post', 'login/', json=self.credentials, headers={'Content-Type': 'application/json'})
            if not res or not res.ok:
                self.error_message = f"{self.user_name} auth err {getattr(res, 'status_code', '')} on '{self.base_url}'"
                return False
            # # noinspection PyUnresolvedReferences
            # assert res.request.user.is_authenticated

            res = self._request('get', 'csrf/')     # put token into self.session.cookies.get('csrftoken')
            token = self.session.cookies.get('csrftoken')
            if not res or not res.ok or not token:
                self.error_message = f"CSRF token '{token}' invalid or not returned from server '{self.base_url}'"
                return False
            self.session.headers['X-CSRFToken'] = token

        self.connected = True
        return True

    def _request(self, method: str, slug: str, **kwargs) -> Optional[requests.Response]:
        """ oaio server request """
        if slug not in ('csrf/', 'login/') and not self._reconnect_check():
            return None

        url = self.base_url + slug
        try:
            met = getattr(self.session, method)
            res = met(url, **kwargs)
            res.raise_for_status()
            self.error_message = ""
            return res
        except (requests.HTTPError, requests.ConnectionError, Exception) as ex:
            if 'json' in kwargs and 'password' in kwargs['json']:   # hide password if in kwargs['json']['password']
                kwargs['json']['password'] = kwargs['json']['password'][:2] + "*" * len(kwargs['json']['password'])
            self.error_message = f"request {method}-method error '{ex}' for URL '{url}' and kwargs={kwargs}"
        return None

    def _save_local_object_info(self, oai_obj: OaiObject):
        """ save oaio to local oaio info. """
        if not oai_obj.client_stamp:    # just downloaded from server
            oai_obj.client_stamp = oai_obj.server_stamp
            oai_obj.client_values = oai_obj.server_values
        elif oai_obj.client_stamp > oai_obj.server_stamp:
            assert not self.unsync_objectz or self.unsync_objectz[-1].client_stamp < oai_obj.client_stamp
            self.unsync_objectz.append(oai_obj)

        self.local_objectz[oai_obj.oaio_id] = oai_obj

        write_file(os.path.join(self.local_root_path, OBJECTS_DIR, oai_obj.oaio_id),
                   repr(object_dict(oai_obj)))

    def _upload_object(self, oai_obj: OaiObject, register: bool = False) -> bool:
        """ send locally changed oaio to content and oaio/web servers and update the specified oai_obj instance.

        :return:                True if upload went well or False on failure or if servers are offline.
        """
        files, cdn_api, client_path, server_path = self._object_client_server_file_paths(oai_obj)
        if cdn_api is None:
            return False

        for file_path in files:
            if not cdn_api.deploy_file(os.path.join(server_path, file_path),
                                       source_path=os.path.join(client_path, file_path)):
                self.error_message = f"{file_path} upload of {oai_obj} to CDN failed with: {cdn_api.error_message}"
                return False

        action = REGISTER_ACTION if register else UPLOAD_ACTION
        res = self._request('post', f'{action}/{oai_obj.oaio_id}', json=object_dict(oai_obj))
        if not res or not res.ok:
            self.error_message = f"object upload of {oai_obj} to server failed."
            return False

        srv_obj = res.json()
        assert srv_obj.get('oaio', {}).get('oaio_id') == oai_obj.oaio_id

        # Pycharm bug https://youtrack.jetbrains.com/issue/PY-76070
        # noinspection PyTypeChecker
        for field in dataclasses.fields(oai_obj):
            field_name = field.name
            setattr(oai_obj, field_name, srv_obj[field_name])   # update field values client_stamp, server_stamp, ...

        return True

    # public api of this client instance ##########################################################

    def register_file(self, file_path: str, cdn_id: OaioCdnIdType = ""):
        """ register new oaio file object.

        :param file_path:       path of the new file object to register.
        :param cdn_id:          content server id or empty string to use default content server.
        """
        self.register_object({FILES_VALUES_KEY: [placeholder_path(file_path)]}, cdn_id=cdn_id)

    def register_folder(self, folder_path: str = "", cdn_id: OaioCdnIdType = ""):
        """ register new oaio folder object.

        :param folder_path:     path of the new folder object to register.
                                using :attr:`.local_root_path` if not specified.
        :param cdn_id:          content server id or empty string to use default content server.
        """
        new_val = {FILES_VALUES_KEY: self._folder_files(folder_path)}
        if folder_path:
            new_val[ROOT_VALUES_KEY] = folder_path
        self.register_object(new_val, cdn_id=cdn_id)

    def register_object(self, values: OaioValuesType, stamp: OaioStampType = "", cdn_id: OaioCdnIdType = ""
                        ) -> Optional[OaiObject]:
        """ register new oaio data object.

        :param values:          values data to register as a new oaio object.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :param cdn_id:          content server id. using default content server if not specified or empty.
        :return:                new OaiObject instance
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        """
        stamp = stamp or now_stamp()

        oaio_id = object_id(user_name=self.user_name, device_id=self.device_id, app_id=self.app_id,
                            stamp=stamp, values=values)

        oai_obj = OaiObject(
            oaio_id=oaio_id,
            cdn_id=cdn_id or self.cdn_default_id,
            client_stamp=stamp,                     # could be changed by server on upload if conflicts with other stamp
            client_values=values,
            cdn_write_access=CREATE_WRITE_ACCESS,   # registering owner has always all access rights
        )

        if self._upload_object(oai_obj, register=True):
            self._save_local_object_info(oai_obj)
            if stamp_diff(self.last_sync_stamp, now_stamp()) > self.auto_sync_seconds:
                self.synchronize_with_server_if_online()
            return oai_obj

        return None

    def synchronize_with_server_if_online(self) -> bool:
        """ synchronize local changes to server and any update/changes done on other clients from server to this client.

        .. hint:: if not connected to the oaio server then this method tries first to (re-)connect.

        :return:                False if the client is offline or on sync error, else True.
        """
        if not self._reconnect_check():
            return False

        error = False

        for oai_obj in self.unsync_objectz[:]:
            if self._upload_object(oai_obj):
                self.unsync_objectz.remove(oai_obj)
            else:
                error = True    # self._upload_object() extended already self.error_message

        for oai_obj in self._changed_server_objectz().values():
            error = not self._download_object(oai_obj) or error

        self.last_sync_stamp = now_stamp()

        return not error

    def update_file(self, oaio_id: OaioIdType, file_path: str = "") -> OaiObject:
        """ update oai file object locally.

        :param oaio_id:         id of the oai file object to update.
        :param file_path:       path of the file oaio.
        :return:                the updated oaio.
        """
        old_val = self.local_objectz[oaio_id].client_values
        assert len(old_val.get(FILES_VALUES_KEY, [])) == 1, "file count error, expected exactly one file"

        if not file_path:
            file_path = old_val[FILES_VALUES_KEY][0]
        assert os.path.isfile(normalize(file_path)), f"updated file {normalize(file_path)} does not exist"

        return self.update_object(oaio_id, {FILES_VALUES_KEY: [placeholder_path(file_path)]})

    def update_folder(self, oaio_id: OaioIdType, added_files: Sequence[str] = (), removed_files: Sequence[str] = ()
                      ) -> OaiObject:
        """ update oai folder object locally.

        :param oaio_id:         id of the oai folder object to update.
        :param added_files:     file paths to be added.
        :param removed_files:   file paths to be removed.
        :return:                the updated oaio.
        """
        values = self.local_objectz[oaio_id].client_values
        if added_files or removed_files:
            assert not (set(added_files) & set(removed_files)), f"duplicates: {set(added_files) & set(removed_files)}"
            assert all(os.path.isfile(normalize(file_path)) for file_path in added_files), ""
            file_paths = values[FILES_VALUES_KEY]
            file_paths.extend([placeholder_path(file_path) for file_path in added_files])
            for file_path in removed_files:
                file_paths.remove(placeholder_path(file_path))

        else:           # check all files for additions/removals
            if ROOT_VALUES_KEY in values:
                root_folder = values[ROOT_VALUES_KEY]
            else:
                root_folder = os.path.join(self.local_root_path, FILES_DIR, oaio_id)
            new_files = self._folder_files(root_folder)
            values[FILES_VALUES_KEY] = new_files

        return self.update_object(oaio_id, values)

    def update_object(self, oaio_id: OaioIdType, values: OaioValuesType, stamp: OaioStampType = "") -> OaiObject:
        """ update oaio data object locally.

        :param oaio_id:         id of the oaio to update.
        :param values:          values of the oaio.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :return:                the updated oaio.
        """
        old_obj = self.local_objectz[oaio_id]
        new_obj = OaiObject(**object_dict(old_obj))

        new_obj.client_stamp = stamp or now_stamp()
        new_obj.client_values = values

        if self._upload_object(new_obj):
            if old_obj.client_stamp == old_obj.server_stamp:
                new_obj.server_values = old_obj.client_values
            self._save_local_object_info(new_obj)

        if stamp_diff(self.last_sync_stamp, now_stamp()) > self.auto_sync_seconds:
            self.synchronize_with_server_if_online()

        return new_obj

    def upsert_subscriber(self, oaio_id: OaioIdType, user_name: str,
                          write_access: OaioCdnWriteAccessType = READ_ONLY_ACCESS) -> int:
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

    def unregister_object(self, oaio_id: OaioIdType):
        """ unregister/delete oai object.

        :param oaio_id:         id of the oaio to unregister.
        """
        oai_obj = self.local_objectz.pop(oaio_id, None)
        if oai_obj is None:
            self.error_message = f"local/client object to delete/unregister with id '{oaio_id}' not found"
            return False

        # noinspection PyUnresolvedReferences,PyTypeChecker
        res = self._request('post', f'{DELETE_ACTION}/{oai_obj.oaio_id}', json=object_dict(oai_obj))
        if not res or not res.ok:
            self.error_message = f"object delete/unregister of {oai_obj} to server failed."
            return False

        if oai_obj in self.unsync_objectz:
            # noinspection PyTypeChecker
            self.unsync_objectz.remove(oai_obj)
        if os.path.isdir(path := os.path.join(self.local_root_path, FILES_DIR, oaio_id)):
            shutil.rmtree(path)
        if os.path.isfile(path := os.path.join(self.local_root_path, OBJECTS_DIR, oaio_id)):
            os.remove(path)
