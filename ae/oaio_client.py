"""
Our Asynchronously Interchangeable Objects Client
=================================================

this portion is providing a client interface to manage asynchronously interchangeable oai objectz.

each oai object has a user definable values dictionary and can optionally have a file or folder attached to it.

an instance of the here implemented class :class:`~ae.oaio_client.OaioClient`, represents a client interface
to the oaio server, a django server `available as git repository <https://gitlab.com/ae-group/oaio_server>`_.
"""
import os
import shutil

from ast import literal_eval
from copy import deepcopy
from typing import Optional, Sequence, cast

import requests

from ae.base import (                                                                                   # type: ignore
    app_name_guess, defuse, mask_secrets, os_device_id, os_path_isdir, os_path_isfile, os_path_join, os_path_relpath,
    os_user_name, read_file, write_file,
    ErrorMsgMixin)
from ae.cloud_storage import CshApiBase, csh_api_class                                                  # type: ignore
from ae.oaio_model import (                                                                             # type: ignore
    CREATE_ACCESS_RIGHT, DELETE_ACTION, FILES_DIR, FILES_VALUES_KEY, MAX_STAMP_DIFF, NO_ACCESS_RIGHT, OBJECTS_DIR,
    OLDEST_SYNC_STAMP, READ_ACCESS_RIGHT, REGISTER_ACTION, ROOT_VALUES_KEY, UPLOAD_ACTION,
    context_encode, now_stamp, object_dict, object_id, stamp_diff,
    OaioAccessRightType, OaioCshIdType, OaioIdType, OaioMapType, OaiObject, OaioStampType, OaioUserIdType,
    OaioValuesType)
from ae.paths import normalize, placeholder_path, Collector                                             # type: ignore


__version__ = '0.3.17'


LAST_SYNC_STAMP_FILE = 'last_sync_stamp.txt'    #: file name to store the last synchronization timestamp


UserzAccessType = list[dict[OaioUserIdType, OaioAccessRightType]]   #: :meth:`OaioClient.userz_access` return value


class OaioClient(ErrorMsgMixin):            # pylint: disable=too-many-instance-attributes
    """ interface to manage creations, updates and deletions of oaio objects of a user.

    .. note:: after creating an instance the :meth:`.synchronize` method has to be called at least once.

    """
    def __init__(self, host: str, credentials: dict[str, str],
                 app_id: str = "",
                 device_id: str = "",
                 csh_default_id: OaioCshIdType = 'Digi',
                 client_root: str = "{usr}/oaio_root/",
                 ):                         # pylint: disable=too-many-arguments, too-many-positional-arguments
        """ initialize a new client instance to connect to the oaio server.

        :param host:            oaio server host name/address and optional port number.
        :param credentials:     oaio server user identification credentials kwargs (dict with the keys
                                'username' and 'password').
        :param app_id:          optional id/name of the app from where the client is connecting from.
                                defaults to :attr:`~ae.core.AppBase.app_name` attribute value (if :mod:`ae.core`
                                got included in project) or (if not set) to the return value of the
                                function :func:`~ae.base.app_name_guess`.
        :param device_id:       id of the client device.
                                defaults to :data:`~ae.base.os_device_id`.
        :param csh_default_id:  id for the default cloud storage server to use.
                                defaults to 'Digi'.
        :param client_root:     path to the folder on the local device where the oaio info and files gets cached.
                                defaults to the placeholder path "{usr}/oaio_root/".
        """
        assert defuse(app_id) == app_id, f"{app_id=} contains invalid characters {set(defuse(app_id)) - set(app_id)=}"
        assert defuse(device_id) == device_id, f"invalid chr {set(defuse(device_id)) - set(device_id)=} in {device_id=}"

        super().__init__()

        self.base_url = 'http' + ('' if host[:9] in ('localhost', '127.0.0.1') else 's') + f'://{host}/api/'
        self.credentials = credentials
        self.user_name = credentials.get('username') or os_user_name()
        self.app_id = app_id or self.cae and self.cae.app_name or app_name_guess()
        self.device_id = device_id or os_device_id
        self.csh_default_id = csh_default_id
        self.client_root = normalize(client_root)

        self.session = requests.Session()
        self.session.headers.update(context_encode(self.user_name, self.device_id, self.app_id))
        self.connected = False

        self._init_client_folders()
        self._last_sync_stamp = ""
        self.client_objectz: OaioMapType = {}

    def __del__(self):
        """ automatic logout and close of the http session. """
        if self.connected:
            self._request('post', 'logout/')
        if self.session:
            self.session.close()

    def _client_file_root(self, oaio_id: OaioIdType, values: OaioValuesType) -> str:
        """ determine the path on client/device where the file(s) attached to an oaio get stored.

        :param oaio_id:         id of the oaio.
        :param values:          oaio values (client_values if upload else server_values).
        :return:                path string.
        """
        if ROOT_VALUES_KEY in values:
            root_folder = normalize(values[ROOT_VALUES_KEY])
        else:
            root_folder = os_path_join(self.client_root, FILES_DIR, oaio_id)
        return root_folder

    def _client_server_file_api_paths(self, oai_obj: OaiObject) -> tuple[list[str], Optional[CshApiBase], str, str]:
        """ get attached files, the cloud storage api id, and the files root paths on client and cloud storage host. """
        values = oai_obj.client_values
        files = values.get(FILES_VALUES_KEY, [])
        csh_id = oai_obj.csh_id
        if not files or not csh_id or (csh_api := self._csh_api(csh_id)) is None:
            if files:
                self.error_message = f"cloud storage {csh_id=} empty/invalid; {oai_obj=}"   # pragma: no cover
            return [], None, "", ""

        oaio_id = oai_obj.oaio_id
        client_path = self._client_file_root(oaio_id, values)
        server_path = os_path_join(oaio_id, oai_obj.client_stamp)

        return files, csh_api, client_path, server_path

    def _csh_api(self, csh_id: OaioCshIdType) -> Optional[CshApiBase]:
        """ determine api and credentials of cloud storage host specified by its id from the web server db/config. """
        res = self._request('get', f'csh_args/{csh_id}')
        if self._res_err(res, f"oaio server error in {csh_id=}-args fetch"):                # pragma: no cover
            return None

        csh_kwargs = res.json()                         # type: ignore # self._res_err ensures that res is not None
        api_class = csh_api_class(csh_id)
        return api_class(**csh_kwargs)

    def _delete_client_object(self, oaio_id: OaioIdType) -> bool:
        """ delete object locally on client from file system and client_objectz dict.

        :param oaio_id:         id of the oaio.
        :return:                True if oaio got deleted successfully locally on client, else False.
        """
        path = os_path_join(self.client_root, OBJECTS_DIR, oaio_id)
        oai_obj = self.client_objectz.pop(oaio_id, None)
        if oai_obj and os_path_isfile(path):
            os.remove(path)
            return True

        self.error_message = f"delete client object integrity error: {path=} {oaio_id=} {oai_obj=}"
        return False

    def _delete_server_object(self, oai_obj: OaiObject) -> bool:
        """ delete oaio object from oaio server.

        :param oai_obj:         :class:`~ae.oaio_model.OaiObject` dataclass instance of the object to delete.
                                (the oaio server view ObjectzDataView only uses the oaio_id field).
        :return:                True if the specified object got deleted from the server,
                                else False (check self.error_message for details).
        """
        # noinspection PyTypeChecker
        res = self._request('post', f'{DELETE_ACTION}/', json=object_dict(oai_obj))     # PyCharm inspection Bug
        return self._res_err(res, f"object delete/unregister to server failed; {oai_obj=}") == ""

    def _download_object(self, oai_obj: OaiObject) -> bool:
        """ save oaio info and download optional attached files to local device/cache.

        :param oai_obj:         :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :return:                True if object info and files got downloaded without errors, else False.
        """
        files, csh_api, client_path, server_path = self._client_server_file_api_paths(oai_obj)
        if files and csh_api is None:                                                       # pragma: no cover
            return False

        for file_path in files:
            assert csh_api is not None  # for mypy
            content = csh_api.deployed_file_content(os_path_join(server_path, file_path))
            if content is None:                                                             # pragma: no cover
                self.error_message = f"cloud storage download error: {csh_api.error_message=} {oai_obj=} {file_path=}"
                return False
            write_file(os_path_join(client_path, file_path), content, make_dirs=True)

        oai_obj.server_stamp = oai_obj.client_stamp
        oai_obj.server_values = deepcopy(oai_obj.client_values)

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
            write_file(file_path, OLDEST_SYNC_STAMP)

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

    def _reconnect_check(self) -> bool:
        """ check if server got already connected and (re)connect if not.

        :return                 True if still connected or successfully reconnected
                                or False if offline, connection cannot be established, CSRF token not available or on
                                any other server login failure/error; in these cases check the message in the property
                                :attr:`~OaioClient.error_message` (inherited from :class:`~ae.base.ErrorMsgMixin`).
        """
        if self.connected:
            res = self._request('get', 'current_stamp/', _in_chk=True)
            if res and res.ok:
                client_stamp = now_stamp()
                server_stamp = res.json().get('current_stamp')
                if abs(stamp_diff(client_stamp, server_stamp)) > MAX_STAMP_DIFF:            # pragma: no cover
                    self.error_message = f"clocks are out of sync; {client_stamp=} {server_stamp=}"
                    self.connected = False
                    return False
                return True

            self.session.headers.pop('X-CSRFToken')                                         # pragma: no cover
            self.connected = False                                                          # pragma: no cover

        if not self.connected:
            res = self._request('post', 'login/', _in_chk=True, json=self.credentials)
            if not self._res_err(res, f"user '{self.user_name}' authentication error"):
                self.connected = True

        return self.connected

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
        res = None
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
                    if err_msg := self._res_err(res, f"CSRF fetch error in {method=} with {url=}",
                                                failure="" if ses_token else ": empty token", add_err=False):
                        raise Exception(err_msg)        # pylint: disable=broad-exception-raised # pragma: no cover
                request_kwargs.setdefault('cookies', {'csrftoken': ses_token})
                self.session.headers['X-CSRFToken'] = cast(str, ses_token)  # w/o cast in types-requests 2.31.0.20240311
                self.session.headers['Referer'] = url               # needed only for https requests

            met = getattr(self.session, method)
            res = met(url, **request_kwargs)
            assert res, f"session {method=} call with {request_kwargs=} returned unexpected empty response {res=}"
            res.raise_for_status()
            self.error_message = ""
            return res

        # pylint: disable-next=broad-exception-caught # pragma: no cover
        except (requests.HTTPError, requests.ConnectionError, AssertionError, Exception) as exception:
            self._res_err(res, f"{method=} {exception=} {url=} {_in_chk=} {mask_secrets(request_kwargs)=}")

        return None

    def _res_err(self, res: Optional[requests.Response], msg: str, failure: str = "", add_err: bool = True) -> str:
        """ web request response error checker, amending error message with status-code. """
        if res and res.ok and not failure:
            return ""

        msg += f"{failure};"
        if res:
            msg += f" {getattr(res, 'status_code', '?')=}"
            try:
                msg += f" {res.json()=}"
            except (AttributeError, Exception):         # pylint: disable=broad-exception-caught # pragma: no cover
                msg += f" {getattr(res, 'content', '¿')=}"

        if add_err:
            self.error_message = msg

        return msg

    def _save_client_object_info(self, oai_obj: OaiObject):
        """ save oaio to local oaio info. """
        oaio_id = oai_obj.oaio_id
        assert oaio_id and oai_obj.client_stamp, f"cannot save oaio ({oai_obj}) locally with empty id or client_stamp"

        self.client_objectz[oaio_id] = oai_obj
        write_file(os_path_join(self.client_root, OBJECTS_DIR, oaio_id), repr(object_dict(oai_obj)))

    def _upload_object(self, oai_obj: OaiObject) -> bool:
        """ save local/client object and try to send changes to storage and oaio/web servers.

        :param oai_obj:         :class:`~ae.oaio_model.OaiObject` dataclass instance to update/upload/register.
        :return:                True if register/upload went well or False on failure or if servers are offline (for
                                details check the error_message attribute of this instance)..
        """
        files, csh_api, client_path, server_path = self._client_server_file_api_paths(oai_obj)
        if files and csh_api is None:
            return False                                                                    # pragma: no cover

        for file_path in files:
            assert csh_api is not None  # for mypy
            if not csh_api.deploy_file(os_path_join(server_path, file_path),
                                       source_path=os_path_join(client_path, file_path)):   # pragma: no cover
                self.error_message = f"'{file_path}' cloud storage upload error: {csh_api.error_message=} {oai_obj=}"
                return False

        action = UPLOAD_ACTION if oai_obj.server_stamp else REGISTER_ACTION
        res = self._request('post', f'{action}/', json=object_dict(oai_obj))
        if self._res_err(res, f"postponed {action} onto server of {oai_obj}"):
            return False                                                                    # pragma: no cover

        srv_dict = res.json()               # type: ignore # self._res_err ensures that res is not None
        assert srv_dict.get('oaio_id') == oai_obj.oaio_id, f"{srv_dict.get('oaio_id')=} not matching {oai_obj.oaio_id=}"

        oai_obj.server_stamp = oai_obj.client_stamp
        oai_obj.server_values = deepcopy(oai_obj.client_values)
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

    def register_file(self, file_name: str,     # pylint: disable=too-many-arguments, too-many-positional-arguments
                      file_content: Optional[bytes] = None, root_path: str = "", stamp: OaioStampType = "",
                      csh_id: OaioCshIdType = "") -> Optional[OaiObject]:
        """ register new oaio file object.

        :param file_name:       name of the new file object to register.
        :param file_content:    file content if file not exists, pass bytes array to create the file.
        :param root_path:       root path on local-machine of the new file object to register.
                                using :attr:`.client_root` if not specified.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param csh_id:          cloud storage server id or empty string to use default cloud storage server.
        :return:                new OaiObject instance
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        :raises AssertionError: if file to register does not exist.
        """
        stamp = stamp or now_stamp()
        values = {FILES_VALUES_KEY: [file_name]}
        if root_path:
            values[ROOT_VALUES_KEY] = placeholder_path(root_path)
            oaio_id = ''
            file_path = normalize(os_path_join(root_path, file_name))
        else:
            oaio_id = object_id(user_name=self.user_name, device_id=self.device_id, app_id=self.app_id,
                                stamp=stamp, values=values)
            root_path = self._client_file_root(oaio_id, values)
            file_path = os_path_join(root_path, file_name)

        if file_content is None:
            assert os_path_isfile(file_path), f"file to register not found: {file_path}"
        else:
            write_file(file_path, file_content, make_dirs=True)

        return self.register_object(values, stamp=stamp, oaio_id=oaio_id, csh_id=csh_id)

    def register_folder(self, root_path: str, stamp: OaioStampType = "",
                        csh_id: OaioCshIdType = "") -> Optional[OaiObject]:
        """ register new oaio folder object.

        :param root_path:       root path on the local-machine/client of the new folder object to register.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param csh_id:          cloud storage server id or empty string to use default cloud storage server.
        :return:                new OaiObject instance
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        :raises AssertionError: if files to register does not exist.
        """
        root_path = normalize(root_path)
        values = {ROOT_VALUES_KEY: placeholder_path(root_path),
                  FILES_VALUES_KEY: self._folder_files(root_path)}

        return self.register_object(values, stamp=stamp, csh_id=csh_id)

    def register_object(self, values: OaioValuesType, stamp: OaioStampType = '',
                        oaio_id: OaioIdType = '', csh_id: OaioCshIdType = '') -> Optional[OaiObject]:
        """ register new oaio data object.

        :param values:          values data to register as a new oaio object.
        :param stamp:           optional timestamp (created by :func:`~ae.oaio_model.now_stamp` if not specified).
        :param oaio_id:         object id (will be created if not passed).
        :param csh_id:          cloud storage server id. using default cloud storage server if not specified or empty.
        :return:                new OaiObject instance.
                                or None if either stamp or oaio_id are already registered (check self.error_message).
        :raises AssertionError: on invalid argument values/types or if the oaio_id got already registered.
        """
        assert isinstance(values, dict), f"register_object(): values arg must be a dict; {values=}"    # OaioValuesType
        stamp = stamp or now_stamp()
        assert stamp > OLDEST_SYNC_STAMP, f"register_object(): too old {stamp=} specified; <= {OLDEST_SYNC_STAMP=}"

        oaio_id = oaio_id or object_id(user_name=self.user_name, device_id=self.device_id, app_id=self.app_id,
                                       stamp=stamp, values=values)
        assert oaio_id not in self.client_objectz, f"register_object(): {oaio_id=} got already registered"

        oai_obj = OaiObject(
            oaio_id=oaio_id,
            client_stamp=stamp,                     # could be changed by server on upload if conflicts with other stamp
            client_values=values,
            csh_id=csh_id or self.csh_default_id,
            username=self.user_name,
            device_id=self.device_id,
            app_id=self.app_id,
            csh_access_right=CREATE_ACCESS_RIGHT,   # registering owner has always all access rights
        )

        self._save_client_object_info(oai_obj)      # store new obj in local OBJECTS_DIR

        if not self.synchronize_with_server_if_online():
            return None                                                                     # pragma: no cover

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
            if cob.client_stamp > cob.server_stamp:             # or cob.server_stamp == ''
                error = not self._upload_object(cob) or error   # _upload_object() extends self.error_message on error

        newer = [_ for _ in soz.values() if coz.get(_.oaio_id, OaiObject(_.oaio_id)).client_stamp < _.client_stamp]
        for sob in sorted(newer, key=lambda _: _.client_stamp):
            error = not self._download_object(sob) or error

        if not error:
            self.last_sync_stamp = now_stamp()

        return not error

    def unregister_object(self, oaio_id: OaioIdType, wipe_files: bool = False) -> str:
        """ unregister/delete oai object.

        :param oaio_id:         id of the oaio to unregister.
        :param wipe_files:      pass True to also remove/wipe all attached file(s) on the local machine.
        :return:                empty string if unregistering was successful, else error message on failure.
        """
        oai_obj = self.client_objectz.get(oaio_id)
        if oai_obj is None:
            self.error_message = f"client object to delete/unregister with id '{oaio_id}' not found"
            return self.error_message

        registered = oai_obj.server_stamp                           # if registered on server
        if registered and not self._delete_server_object(oai_obj):  # check and return errors on deleting server object
            return self.error_message

        if self._delete_client_object(oaio_id):
            if wipe_files:
                files, csh_api, client_path, server_path = self._client_server_file_api_paths(oai_obj)
                if files:
                    if registered:
                        err_msg = csh_api.delete_file_or_folder(server_path)    # type: ignore # csh_api is not None
                        if err_msg:
                            self.error_message = err_msg
                            return self.error_message
                    if os_path_isdir(client_path):
                        shutil.rmtree(client_path)

            self.synchronize_with_server_if_online()

        return self.error_message

    def unsubscribe(self, oaio_id: OaioIdType, user_name: OaioUserIdType) -> str:
        """ remove subscription of an oai object for a user.

        :param oaio_id:         id of the oaio to unsubscribe.
        :param user_name:       name of the subscribed user.
        :return:                empty string if subscription could be removed without error, else error message.
        """
        data = {'oaio_id': oaio_id, 'username': user_name, 'access_right': NO_ACCESS_RIGHT}
        res = self._request('post', 'subscribe/', json=data)
        if not self._res_err(res, f"unsubscribe of {user_name=} and {oaio_id=} failed"):
            if user_name == self.user_name:
                self._delete_client_object(oaio_id)

        return self.error_message

    def update_file(self, oaio_id: OaioIdType,  # pylint: disable=too-many-arguments, too-many-positional-arguments
                    file_name: str = "", file_content: Optional[bytes] = None, root_path: str = "",
                    stamp: OaioStampType = "") -> OaiObject:
        """ update oai file object locally.

        :param oaio_id:         id of the oai file object to update.
        :param file_name:       name (optionally with subdirectories path) of the attached file.
        :param file_content:    file content if file name not exists, pass bytes array to create the file.
        :param root_path:       root path on local-machine of the new file object to update.
                                using :attr:`.client_root` if not specified.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :raises AssertionError: if file to update does not exist.
        """
        values = deepcopy(self.client_objectz[oaio_id].client_values)
        if file_name:
            values[FILES_VALUES_KEY] = [file_name]
        else:
            file_name = values[FILES_VALUES_KEY][0]
        if root_path:
            values[ROOT_VALUES_KEY] = placeholder_path(root_path)
        elif ROOT_VALUES_KEY in values:
            root_path = values[ROOT_VALUES_KEY]
        else:
            root_path = self._client_file_root(oaio_id, values)

        file_path = normalize(os_path_join(root_path, file_name))

        if file_content is None:
            assert os_path_isfile(file_path), f"file to update does not exist in {file_path=}"
        else:
            write_file(file_path, file_content, make_dirs=True)

        return self.update_object(oaio_id, values, stamp=stamp)

    def update_folder(self, oaio_id: OaioIdType, root_path: str = "", stamp: OaioStampType = "") -> OaiObject:
        """ update oai folder object locally.

        :param oaio_id:         id of the oai folder object to update.
        :param root_path:       new root path on local-machine of the new folder object to update.
                                using current root path if not specified.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :raises AssertionError: if same file is in add_files and in removed_files,
                                or if one of the files to update does not exist.
        """
        values = deepcopy(self.client_objectz[oaio_id].client_values)
        if root_path:
            values[ROOT_VALUES_KEY] = placeholder_path(root_path)

        client_root = self._client_file_root(oaio_id, values)
        values[FILES_VALUES_KEY] = self._folder_files(client_root)

        return self.update_object(oaio_id, values, stamp=stamp)

    def update_object(self, oaio_id: OaioIdType, values: OaioValuesType, stamp: OaioStampType = "", reset: bool = False
                      ) -> OaiObject:
        """ update oaio data object locally.

        :param oaio_id:         id of a registered oaio to update.
        :param values:          values to update within the oaio.
        :param stamp:           optional timestamp (using :func:`~ae.oaio_model.now_stamp` if not specified).
        :param reset:           pass True to reset the values before they get updated with the values
                                specified in :paramref:`~update_object.values`.
        :return:                the updated :class:`~ae.oaio_model.OaiObject` dataclass instance.
        :raises AssertionError: on invalid argument values/types or if the oaio_id did not get registered.
        """
        assert oaio_id in self.client_objectz, f"update_object(): oaio object with id '{oaio_id}' not registered"
        oai_obj = self.client_objectz[oaio_id]
        assert oai_obj.client_stamp, f"update_object(): oai object {oaio_id=} has empty client_stamp; {oai_obj=}"

        if stamp:
            assert stamp > OLDEST_SYNC_STAMP, f"update_object(): too old stamp {stamp} specified; <={OLDEST_SYNC_STAMP}"
        else:                                                                               # pragma: no cover
            stamp = now_stamp()

        assert stamp > oai_obj.client_stamp, f"update_object(): got too old stamp {stamp}; > {oai_obj.client_stamp}"
        oai_obj.client_stamp = stamp

        if reset:
            oai_obj.client_values.clear()
        oai_obj.client_values.update(values)

        self._save_client_object_info(oai_obj)
        self.synchronize_with_server_if_online()

        return oai_obj

    def upsert_subscription(self, oaio_id: OaioIdType, user_name: OaioUserIdType,
                            access_right: OaioAccessRightType = READ_ACCESS_RIGHT) -> int:
        """ add/delete subscriber of an oai object or update the access right of an existing user subscription.

        :param oaio_id:         id of the oaio to subscribe to or to unsubscribe from.
        :param user_name:       name of the un-/subscribing user.
        :param access_right:    either :data:`~ae.oaio_model.NO_ACCESS_RIGHT` to unsubscribe user
                                or a user access right (one of :data:`~ae.oaio_model.ACCESS_RIGHTS`) to subscribe
                                the oaio specified by :paramref:`~upsert_subscription.oaio_id`
                                to a user specified by :paramref:`~upsert_subscription.user_name`.
                                e.g. to grant update rights pass the value :data:`~ae.oaio_model.UPDATE_ACCESS_RIGHT`.
                                if not specified then the value :data:`~ae.oaio_model.READ_ACCESS_RIGHT` will be used.
        :return:                the primary key integer value (Pubz.Pid) of the added/updated Pubz subscription record
                                or 0/zero if an error occurred.
        """
        data = {'oaio_id': oaio_id, 'username': user_name, 'access_right': access_right}
        res = self._request('post', 'subscribe/', json=data)    # json-kwarg implies content-type 'application/json' hdr
        if self._res_err(res, f"subscription of {user_name=} for {oaio_id=} failed"):
            return 0
        return res.json().get('Pid', 0)     # type: ignore # self._res_err ensures that res is not None

    def userz_access(self, oaio_id: OaioIdType) -> UserzAccessType:
        """ determine a list of all the registered users and their access right to the specified oaio.

        :param oaio_id:         id of the oaio determine users and access rights for
                                or an empty or unregistered oaio id if the oaio is not yet registered.
        :return:                list of dicts with the keys 'username' and 'access_right', or empty list on error. the
                                returned list is sorted by the access_right (create, delete, update, read) and username.
                                if an empty/unregistered oaio id got specified all registered userz will be returned
                                with the :data:`~ae.oaio_model.NO_ACCESS_RIGHT` access right.
        """
        res = self._request('get', f'user_subz/{oaio_id or "_not__existing__oaio_id_"}')
        warn_msg = self._res_err(res, f"Warning: OaioClient.userz_access() error; {oaio_id=}", add_err=False)
        if warn_msg:
            self.vpo(warn_msg)
            return []

        assert res, "for mypy - not seeing that self._res_err is checking res and returning empty string if not None"
        return sorted(res.json(), key=lambda _: _['access_right'] + _['username'])

    def wipe_user(self, user_name: OaioUserIdType) -> str:
        """ wipe the specified user including all its objects, subscriptions and log entries.

        :param user_name:       name of the subscribing user to be wiped from the database.
        :return:                empty string if user including its subscription and log entries could be removed,
                                else the error message.
        """
        res = self._request('post', 'wipe_user/', json={'Uid': user_name})
        self._res_err(res, f"wipe of user '{user_name}' failed")
        return self.error_message
