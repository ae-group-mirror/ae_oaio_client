""" unit/integration tests of the oaio client package. """
import os
import shutil
from typing import Any, Optional, cast
from unittest.mock import MagicMock, patch

import pytest
import requests

from ae.base import (
    TESTS_FOLDER, app_name_guess, load_dotenvs, os_device_id, os_path_abspath, os_path_dirname, os_path_isdir,
    os_path_isfile, os_path_join, os_user_name, read_file, write_file)
from ae.cloud_storage import CshApiBase, DigiApi
from ae.oaio_model import (
    CREATE_ACCESS_RIGHT, DELETE_ACTION, FILES_DIR, FILES_VALUES_KEY, HTTP_HEADER_USR_ID, OBJECTS_DIR, REGISTER_ACTION,
    ROOT_VALUES_KEY, UPDATE_ACCESS_RIGHT, UPLOAD_ACTION,
    now_stamp, object_dict,
    OaiObject)
from ae.paths import normalize, placeholder_path

from ae.oaio_client import LAST_SYNC_STAMP_FILE, OaioClient


load_dotenvs()


class TestInstantiation:
    """ client instantiation tests running on local machine and git/CI host, independent of mocked and live servers. """
    def test_args(self):
        cre_args = {'cre_key': 'cre_val'}
        tst_root = os_path_join(TESTS_FOLDER, 'tst')
        loc_path = os_path_join(tst_root, 'root/path')

        try:
            ocl = OaioClient("hOsT", cre_args, app_id='app_id', device_id='dev_id', csh_default_id='csh_id',
                             client_root=loc_path)

            assert "hOsT" in ocl.base_url
            assert ocl.credentials == cre_args
            assert ocl.app_id == 'app_id'
            assert ocl.device_id == 'dev_id'
            assert ocl.csh_default_id == 'csh_id'
            assert ocl.client_root == normalize(loc_path)

            assert os_path_isdir(os_path_join(loc_path, OBJECTS_DIR))
            assert os_path_isdir(os_path_join(loc_path, FILES_DIR))
            assert os_path_isfile(os_path_join(loc_path, LAST_SYNC_STAMP_FILE))

        finally:
            if os_path_isdir(tst_root):
                shutil.rmtree(tst_root)

    def test_args_defaults(self):
        ocl = OaioClient("", {})

        assert ocl.user_name == os_user_name()
        assert ocl.app_id == app_name_guess()
        assert ocl.device_id == os_device_id
        assert ocl.csh_default_id == 'Digi'
        assert ocl.client_root == normalize("{usr}/oaio_root/")

    def test_invalid_host_instantiation_args(self):
        ocl = OaioClient("", {})

        assert ocl
        assert not ocl.synchronize_with_server_if_online()


# ******   test environment for mocked unit and live integration tests   ******

other_user = 'tst_oth_usr'      # other user, for subscription sharing tests


def _csh_file_content(client_obj: OaioClient, oai_obj: OaiObject, file_count: int = 1) -> dict[str, bytes]:
    """ download content of attached file(s) from mocked or live cloud storage host. """
    # noinspection PyProtectedMember
    files, csh_api, client_path, server_path = client_obj._client_server_file_api_paths(oai_obj)
    assert csh_api
    assert len(files) == file_count

    return {fil: csh_api.deployed_file_content(os_path_join(server_path, fil)) for fil in files}


def _csh_file_remove(client_obj: OaioClient, oai_obj: OaiObject, file_count: int = 1) -> str:
    """ delete file content from mocked or live cloud storage host. """
    # noinspection PyProtectedMember
    files, csh_api, client_path, server_path = client_obj._client_server_file_api_paths(oai_obj)
    err_msg = client_obj.error_message
    if not csh_api:
        err_msg += "cloud storage host api could not be determined"
    if len(files) != file_count:
        err_msg += f"files count mismatch: {len(files)} != {file_count}"

    for fil in files:
        err_msg += csh_api.delete_file_or_folder(os_path_join(server_path, fil))
    err_msg += csh_api.delete_file_or_folder(os_path_dirname(server_path))  # also remove the folder named as oaio_id

    return err_msg


# ******   test environment for mocked unit tests   *******************************


EMPTY_FOLDER = "FOLDER HAS NO CONTENT: simulated directory left to allow separate deletion of it in tests"
CSH_API_ID = 'CshMock'          # referring to mock cloud storage class :class:`CshMockApi`
deployed_file_contents = {}     # keep/publish test files in mocked cloud storage for assertions

def _csh_mock_cleared_errors():
    err_msg = ""
    if not all(content == EMPTY_FOLDER for _file, content in deployed_file_contents.items()):
        files_left = {fi: co for fi, co in deployed_file_contents.items() if co != EMPTY_FOLDER}
        err_msg += f"_csh_mock_cleared_errors() found deployed and uncleared test files: {files_left}"
    return err_msg

class CshMockApi(CshApiBase):
    """ simulating dummy cloud storage server - available via :func:`csh_api_class` with id=='CshMock' """
    def __init__(self, **csh_args):
        super().__init__(**csh_args)
        self.csh_args = csh_args
        self.deployed_file_contents = deployed_file_contents

    def deployed_file_content(self, file_path: str) -> Optional[bytes]:
        ret = self.deployed_file_contents.get(file_path)
        if ret is None:
            self.error_message = f"CshMock-content-error: {file_path} not in {self.deployed_file_contents}"
        return ret

    def deploy_file(self, file_path: str, source_path: str = '') -> str:
        path = source_path or file_path
        if not os_path_isfile(path):
            self.error_message = f"CshMock-deploy-error: file '{path}' not found; id='{file_path}' src='{source_path}'"
            return ""

        content = read_file(path, extra_mode='b')
        self.deployed_file_contents[file_path] = content
        return file_path

    def delete_file_or_folder(self, file_path: str) -> str:
        files = self.deployed_file_contents
        found = files.pop(file_path, None) is not None
        if not found:
            for nam in files.copy().keys():
                if nam.startswith(file_path + '/'):
                    files.pop(nam)
                    found = True
            if not found:
                self.error_message = f"CshMock-delete-error {file_path} not in {files}"

        if found and len(left_parts := file_path.split('/')) > 2:
            dir_path = '/'.join(left_parts[:-1]) + '/'
            files[dir_path] = EMPTY_FOLDER

        return self.error_message

registered_oai_objectz: dict[str, OaiObject] = {}

def _mocked_get_or_post_success_response(url: str, **kwargs) -> requests.Response:
    """ requests.Session().get/.post method response mocks, simulating oaio server. """
    mock_res = MagicMock()
    mock_res.ok = True
    mock_res.status_code = 200
    mock_res.raise_for_status.return_value = None

    act_slug = url.split('/')[-2]
    if act_slug == 'current_stamp':
        mock_res.json.return_value = {'current_stamp': now_stamp()}
    elif act_slug == 'csh_args':
        mock_res.json.return_value = {}
    elif act_slug == REGISTER_ACTION:
        oai_obj = OaiObject(**kwargs['json'])
        registered_oai_objectz[oai_obj.oaio_id] = oai_obj
        mock_res.json.return_value = kwargs['json']
    elif act_slug == UPLOAD_ACTION:
        oai_obj = OaiObject(**kwargs['json'])
        registered_oai_objectz[oai_obj.oaio_id] = oai_obj
        mock_res.json.return_value = kwargs['json']
    elif act_slug == DELETE_ACTION:
        oai_obj = OaiObject(**kwargs['json'])
        registered_oai_objectz.pop(oai_obj.oaio_id)
        mock_res.json.return_value = kwargs['json']
    elif act_slug == 'oaio_stampz':
        mock_res.json.return_value = sorted((object_dict(_) for _ in registered_oai_objectz.values()),
                                            key=lambda _: _['client_stamp'])
    elif act_slug == 'subscribe':
        pid = 369963
        mock_res.json.return_value = {'Pid': pid, 'message': f"Pid:{pid} PUid/POid:{kwargs['json']}"}
    elif act_slug == 'user_subz':
        mock_res.json.return_value = [{'username': 'mocked_username', 'access_right': CREATE_ACCESS_RIGHT}]
    elif act_slug == 'wipe_user':
        mock_res.json.return_value = {'message': f"mocked success for wipe user {kwargs}"}
    elif 'json' in kwargs:
        mock_res.json.return_value = kwargs['json']
    else:                                                   # action slugs: DOWNLOAD_ACTION, 'login', 'logout'
        mock_res.json.return_value = {'message': f"mocked success for url {url} and {kwargs=}"}

    return mock_res

def _mocked_get_or_post_failure_response(url: str, **kwargs) -> requests.Response:
    """ requests.Session().get/.post method response mocks, returning error """
    mock_res = MagicMock()
    mock_res.ok = False
    mock_res.status_code = 489
    mock_res.json.return_value = {'e_r_r': f"mocked error for url {url} and {kwargs=}"}
    return mock_res

def user_client(usr_name: str):
    """ provide OaioClient instances simulating the specified user, connected to mocked oaio and cloud storage servers.

    the yield value is the OaioClient instance of the primary user.
    used as fixture via yield from for username parameterized unit tests.
    running also in CI tests on git repo host.

    referred and mocked `response` instance attributes and methods: ok, status_code, json(), raise_for_status()
    """
    cli_root = os_path_join(TESTS_FOLDER, f'uTstOC_root_{usr_name}')    # Oaio Client Unit Test Root of usr_nam
    with patch('ae.oaio_client.requests') as mock_req:
        mock_ses_cls = MagicMock()
        mock_req.Session = mock_ses_cls
        mock_ses_ins = mock_ses_cls.return_value
        mock_ses_ins.get.side_effect = _mocked_get_or_post_success_response
        mock_ses_ins.post.side_effect = _mocked_get_or_post_success_response

        ocl = OaioClient('any_host:8769', {'username': usr_name, 'password': 'any_password'},
                         app_id='aId', device_id='dId',
                         csh_default_id=CSH_API_ID,  # -> mocked class CshMockApi in this module
                         client_root=cli_root,
                         )
        ocl.o_synchronize_with_server_if_online = ocl.synchronize_with_server_if_online
        ocl.synchronize_with_server_if_online = lambda: True  # monkey patch to allow manual server sync in tests

        assert ocl.error_message == ""
        assert os_path_isdir(cli_root)

        yield cast(Any, ocl)

        if os_path_isdir(cli_root):
            shutil.rmtree(cli_root)
        registered_oai_objectz.clear()
        deployed_file_contents.clear()

@pytest.fixture
def mocked_client(request):
    """ OaioClient instance for user uId """
    yield from user_client('uId')

@pytest.fixture
def other_client(mocked_client):
    """ OaioClient instance for user adaUsr """
    yield from user_client('adaUsr')


class TestOaioClientWithMockedServers:
    def test_mocked_client_initialization(self, mocked_client):
        assert mocked_client
        assert not mocked_client.error_message
        assert mocked_client.csh_default_id == CSH_API_ID
        assert not deployed_file_contents
        assert len(mocked_client.client_objectz) == 0

    def test_last_sync_stamp(self, mocked_client):
        assert mocked_client.last_sync_stamp
        stamp = now_stamp()
        mocked_client.last_sync_stamp = stamp
        assert mocked_client.last_sync_stamp == stamp

    def test_register_file(self, mocked_client):
        oai_obj = None
        stamp = now_stamp()
        dir_path = ""
        fil_name = 'tst_fil.xxx'
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"

        assert mocked_client.o_synchronize_with_server_if_online()
        local_object_count = len(mocked_client.client_objectz)

        try:
            oai_obj = mocked_client.register_file(fil_name, file_content=fil_content, stamp=stamp)

            oaio_id = oai_obj.oaio_id
            dir_path = mocked_client._client_file_root(oaio_id, oai_obj.client_values)
            assert mocked_client.error_message == ""
            assert oai_obj is not None
            assert oaio_id
            assert oai_obj.csh_id

            assert ROOT_VALUES_KEY not in oai_obj.client_values
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert os_path_isfile(os_path_join(dir_path, fil_name))
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(mocked_client.client_objectz) == local_object_count + 1
            assert oaio_id in mocked_client.client_objectz
            assert mocked_client.client_objectz[oaio_id] == oai_obj

            assert mocked_client.o_synchronize_with_server_if_online()
            assert _csh_file_content(mocked_client, oai_obj) == {fil_name: fil_content}

        finally:
            if os_path_isdir(dir_path):
                shutil.rmtree(dir_path)
            if oai_obj:
                assert _csh_file_remove(mocked_client, oai_obj) == "", "ERR:" + mocked_client.error_message
                assert _csh_mock_cleared_errors() == ""
                assert mocked_client.unregister_object(oai_obj.oaio_id) == "", "ERR:" + mocked_client.error_message
                assert len(mocked_client.client_objectz) == local_object_count, "ERR:" + mocked_client.error_message

    def test_register_file_with_root(self, mocked_client):
        oai_obj = None
        stamp = now_stamp()
        dir_path = os_path_abspath(os_path_join(TESTS_FOLDER, 'regFileWithRootDir'))
        fil_name = 'tst_fil.tst'
        fil_path = os_path_join(dir_path, fil_name)
        fil_content = b"test file \x00 having binary content \x01\x02\x03\xff"

        assert mocked_client.o_synchronize_with_server_if_online()
        local_object_count = len(mocked_client.client_objectz)

        try:
            write_file(fil_path, fil_content, make_dirs=True)

            oai_obj = mocked_client.register_file(fil_name, root_path=dir_path, stamp=stamp)
            assert mocked_client.error_message == ""
            assert oai_obj is not None

            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == dir_path
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(mocked_client.client_objectz) == local_object_count + 1
            assert oai_obj.oaio_id in mocked_client.client_objectz
            assert mocked_client.client_objectz[oai_obj.oaio_id] == oai_obj

            assert os_path_isfile(fil_path)

            assert mocked_client.o_synchronize_with_server_if_online()
            assert _csh_file_content(mocked_client, oai_obj) == {fil_name: fil_content}

        finally:
            if os_path_isdir(dir_path):
                shutil.rmtree(dir_path)
            if oai_obj:
                assert _csh_file_remove(mocked_client, oai_obj) == "", "ERR:" + mocked_client.error_message
                assert _csh_mock_cleared_errors() == ""
                assert mocked_client.unregister_object(oai_obj.oaio_id) == "", "ERR:" + mocked_client.error_message
                assert len(mocked_client.client_objectz) == local_object_count

    def test_register_folder_with_root(self, mocked_client):
        stamp = now_stamp()
        # noinspection PyTypeChecker
        root_path = os_path_abspath(os_path_join(mocked_client.client_root, FILES_DIR))
        sub_dirs = ['sub_dir1', 'sub_dir3/sub_sub_dir']
        file_paths = ['tst_fil.tst',
                      os_path_join(sub_dirs[0], 'tst_sub1_fil.tst'),
                      os_path_join(sub_dirs[1], 'tst_sub3_sub_fil.tst'),
                      ]
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"

        assert mocked_client.o_synchronize_with_server_if_online()
        local_object_count = len(mocked_client.client_objectz)
        csh_api = mocked_client._csh_api(mocked_client.csh_default_id)
        oaio_id = ""

        try:
            for fil_nam in file_paths:
                write_file(os_path_join(root_path, fil_nam), fil_content + fil_nam.encode(), make_dirs=True)

            oai_obj = mocked_client.register_folder(root_path, stamp=stamp)

            assert oai_obj is not None
            oaio_id = oai_obj.oaio_id
            assert oaio_id
            assert mocked_client.error_message == ""

            svr_path = os_path_join(oaio_id, stamp)
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == normalize(root_path)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(root_path, fil_nam)))
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(mocked_client.client_objectz) == local_object_count + 1
            assert oaio_id in mocked_client.client_objectz
            assert mocked_client.client_objectz[oaio_id] == oai_obj

            assert mocked_client.o_synchronize_with_server_if_online()
            for fil_nam in file_paths:
                assert csh_api.deployed_file_content(os_path_join(svr_path, fil_nam)) == fil_content + fil_nam.encode()

        finally:
            if os_path_isdir(root_path):
                shutil.rmtree(root_path)
            err_msg = "ERR:" + mocked_client.error_message
            if oaio_id:
                assert mocked_client.unregister_object(oaio_id, wipe_files=True) == "", err_msg
                assert len(mocked_client.client_objectz) == local_object_count, err_msg

    def test_register_object(self, mocked_client):
        oai_obj = None
        try:
            oai_obj = mocked_client.register_object({})
            assert mocked_client.o_synchronize_with_server_if_online()

            assert not mocked_client.error_message
            assert oai_obj
            assert oai_obj.oaio_id
            assert oai_obj.client_stamp
            assert oai_obj.client_values == {}
            assert oai_obj.csh_id == CSH_API_ID

            assert not deployed_file_contents, "ERR:" + mocked_client.error_message

            path = os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id)
            assert os_path_isfile(path)

            oai_obj = mocked_client._load_client_object_info(oai_obj.oaio_id)
            assert oai_obj.oaio_id == oai_obj.oaio_id
            assert oai_obj.client_stamp == oai_obj.client_stamp
            assert oai_obj.client_values == oai_obj.client_values
            assert oai_obj.csh_id == oai_obj.csh_id

        finally:
            if oai_obj:
                mocked_client.unregister_object(oai_obj.oaio_id, wipe_files=True)
                assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_synchronize_with_server_if_online(self, mocked_client):
        assert mocked_client.o_synchronize_with_server_if_online() is True

    def test_synchronize_with_server_if_online_with_2nd_usr(self, mocked_client, other_client):
        reg_stamp = now_stamp()
        reg_val = {'reg_key': 'reg_val'}

        oai_obj = mocked_client.register_object(reg_val, stamp=reg_stamp)
        assert oai_obj and mocked_client.o_synchronize_with_server_if_online()
        oaio_id = oai_obj.oaio_id

        syn_obj = mocked_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == reg_stamp
        assert syn_obj.server_stamp == reg_stamp
        assert syn_obj.client_values == reg_val
        assert syn_obj.server_values == reg_val
        assert syn_obj == mocked_client._load_client_object_info(oaio_id)

        assert mocked_client.upsert_subscription(oaio_id, other_client.user_name)
        assert other_client.o_synchronize_with_server_if_online()
        upd_stamp = now_stamp()
        upd_val = {'upd_key': 'upd_val'}

        _upd_obj = other_client.update_object(oaio_id, upd_val, stamp=upd_stamp, reset=True)

        syn_obj = other_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == reg_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == reg_val
        assert syn_obj == other_client._load_client_object_info(oaio_id)

        assert other_client.o_synchronize_with_server_if_online()   # 2nd user uploading updated values to server

        syn_obj = other_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == upd_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == upd_val
        assert syn_obj == other_client._load_client_object_info(oaio_id)

        assert mocked_client.o_synchronize_with_server_if_online()  # registering creator updated by other_client

        syn_obj = mocked_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == upd_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == upd_val
        assert syn_obj == mocked_client._load_client_object_info(oaio_id)

    def test_synchronize_with_server_if_online_with_2nd_usr_file(self, mocked_client, other_client):
        reg_stamp = now_stamp()
        reg_name = 'reg_syn_with_download.tst'
        reg_content = b"register content of tst_syn_with_file"

        oai_obj = mocked_client.register_file(reg_name, file_content=reg_content, stamp=reg_stamp)
        assert oai_obj and mocked_client.o_synchronize_with_server_if_online()
        oaio_id = oai_obj.oaio_id
        reg_val = oai_obj.client_values
        fil_root = os_path_join(mocked_client.client_root, FILES_DIR, oaio_id)
        oth_root = os_path_join(other_client.client_root, FILES_DIR, oaio_id)

        syn_obj = mocked_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == reg_stamp
        assert syn_obj.server_stamp == reg_stamp
        assert syn_obj.client_values == reg_val
        assert syn_obj.server_values == reg_val
        assert syn_obj == mocked_client._load_client_object_info(oaio_id)
        # noinspection PyTypeChecker
        assert read_file(os_path_join(fil_root, reg_name), extra_mode='b') == reg_content

        assert mocked_client.upsert_subscription(oaio_id, other_client.user_name)
        assert other_client.o_synchronize_with_server_if_online()
        upd_stamp = now_stamp()
        upd_name = 'upd_syn_file.name'
        upd_content = b"updated synFileContent"

        upd_obj = other_client.update_file(oaio_id, file_name=upd_name, file_content=upd_content, stamp=upd_stamp)

        assert upd_obj
        upd_val = upd_obj.client_values
        syn_obj = other_client.client_objectz[oaio_id]
        assert syn_obj.oaio_id == oaio_id
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == reg_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == reg_val
        assert syn_obj == other_client._load_client_object_info(oaio_id)
        # noinspection PyTypeChecker
        assert read_file(os_path_join(oth_root, upd_name), extra_mode='b') == upd_content

        assert other_client.o_synchronize_with_server_if_online()

        syn_obj = other_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == upd_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == upd_val
        assert syn_obj == other_client._load_client_object_info(oaio_id)
        # noinspection PyTypeChecker
        assert read_file(os_path_join(oth_root, upd_name), extra_mode='b') == upd_content

        assert mocked_client.o_synchronize_with_server_if_online()

        syn_obj = mocked_client.client_objectz[oaio_id]
        assert syn_obj.client_stamp == upd_stamp
        assert syn_obj.server_stamp == upd_stamp
        assert syn_obj.client_values == upd_val
        assert syn_obj.server_values == upd_val
        assert syn_obj == mocked_client._load_client_object_info(oaio_id)
        # noinspection PyTypeChecker
        assert read_file(os_path_join(fil_root, upd_name), extra_mode='b') == upd_content

    def test_unregister_object(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        assert oai_obj
        assert oai_obj.oaio_id in mocked_client.client_objectz
        assert mocked_client.o_synchronize_with_server_if_online()

        assert mocked_client.unregister_object(oai_obj.oaio_id) == ""

        assert oai_obj.oaio_id not in mocked_client.client_objectz
        assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_unregister_object_not_registered_on_servers(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        assert oai_obj
        assert oai_obj.oaio_id in mocked_client.client_objectz

        assert mocked_client.unregister_object(oai_obj.oaio_id) == ""

        assert oai_obj.oaio_id not in mocked_client.client_objectz
        assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_unregister_object_file_wipe(self, mocked_client):
        reg_name = 'tst_unregister_wiped_file.txt'
        oai_obj = mocked_client.register_file(reg_name, file_content=b"unregister wipe err test file content")
        assert mocked_client.o_synchronize_with_server_if_online()

        err_msg = mocked_client.unregister_object(oai_obj.oaio_id, wipe_files=True)

        assert not err_msg
        assert oai_obj.oaio_id not in mocked_client.client_objectz
        assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))
        assert not os_path_isdir(os_path_join(mocked_client.client_root, FILES_DIR, oai_obj.oaio_id))
        assert not os_path_isfile(os_path_join(mocked_client.client_root, FILES_DIR, oai_obj.oaio_id, reg_name))
        assert _csh_file_content(mocked_client, oai_obj) == {reg_name: None}

    def test_unregister_object_file_wipe_err(self, mocked_client):
        reg_name = 'tst_unregister_wiped_file.txt'
        oai_obj = mocked_client.register_file(reg_name, file_content=b"unregister wipe err test file content")
        assert mocked_client.o_synchronize_with_server_if_online()
        assert _csh_file_remove(mocked_client, oai_obj) == ""  # force error by removing file from the cloud storage
        assert _csh_mock_cleared_errors() == ""

        err_msg = mocked_client.unregister_object(oai_obj.oaio_id, wipe_files=True)

        assert reg_name in err_msg
        assert oai_obj.oaio_id in err_msg

    def test_unregister_object_map_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        mocked_client.client_objectz.pop(oai_obj.oaio_id)

        err_msg = mocked_client.unregister_object(oai_obj.oaio_id)

        assert oai_obj.oaio_id in err_msg

    def test_unregister_server_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        assert mocked_client.o_synchronize_with_server_if_online()
        mocked_client.session.post.side_effect = _mocked_get_or_post_failure_response

        err_msg = mocked_client.unregister_object(oai_obj.oaio_id)

        assert oai_obj.oaio_id in err_msg

    def test_unsubscribe(self, mocked_client):
        oai_obj = mocked_client.register_object({})

        assert mocked_client.unsubscribe(oai_obj.oaio_id, oai_obj.username) == ""

        assert oai_obj.oaio_id not in mocked_client.client_objectz
        assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_unsubscribe_client_obj_file_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        os.remove(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

        err_msg = mocked_client.unsubscribe(oai_obj.oaio_id, oai_obj.username)

        assert oai_obj.oaio_id in err_msg
        assert oai_obj.username in err_msg

    def test_unsubscribe_client_obj_map_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        mocked_client.client_objectz.pop(oai_obj.oaio_id)

        err_msg = mocked_client.unsubscribe(oai_obj.oaio_id, oai_obj.username)

        assert oai_obj.oaio_id in err_msg
        assert oai_obj.username in err_msg

    def test_unsubscribe_server_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        mocked_client.session.post.side_effect = _mocked_get_or_post_failure_response

        err_msg = mocked_client.unsubscribe(oai_obj.oaio_id, oai_obj.username)

        assert oai_obj.oaio_id in err_msg
        assert oai_obj.username in err_msg

    def test_update_file(self, mocked_client):
        oai_obj = None
        dir_path = os_path_abspath(os_path_join(TESTS_FOLDER, 'tst_file_dir'))
        fil_name = 'tst_fil.tst'
        fil_path = os_path_join(dir_path, fil_name)
        fil_content = b"update test file \x00 having binary content \x01\x02\x03\xff"

        try:
            reg_stamp = now_stamp()
            write_file(fil_path, b"", make_dirs=True)
            oai_obj = mocked_client.register_file(fil_name, root_path=dir_path, stamp=reg_stamp)
            assert mocked_client.error_message == ""
            assert oai_obj is not None
            assert mocked_client.o_synchronize_with_server_if_online()
            assert _csh_file_content(mocked_client, oai_obj) == {fil_name: b""}

            write_file(fil_path, fil_content)
            upd_stamp = now_stamp()

            oai_obj = mocked_client.update_file(oai_obj.oaio_id, stamp=upd_stamp)
            assert mocked_client.o_synchronize_with_server_if_online()

            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == dir_path
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert oai_obj.client_stamp == upd_stamp
            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.client_values == oai_obj.server_values
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(mocked_client.client_objectz) == 1
            assert oai_obj.oaio_id in mocked_client.client_objectz

            assert os_path_isfile(fil_path)
            assert _csh_file_content(mocked_client, oai_obj) == {fil_name: fil_content}

        finally:
            if os_path_isdir(dir_path):
                shutil.rmtree(dir_path)
            if oai_obj:
                assert mocked_client.unregister_object(oai_obj.oaio_id) == "", "ERR:" + mocked_client.error_message
                assert len(mocked_client.client_objectz) == 0

    def test_update_file_and_root(self, mocked_client):
        oai_obj = None
        reg_root = mocked_client.client_root
        upd_root = os_path_join(TESTS_FOLDER, 'upd_root')
        reg_name = 'reg_fil.tst'
        upd_name = 'upd_fil.tst'
        reg_path = os_path_join(reg_root, reg_name)
        upd_path = os_path_join(upd_root, upd_name)
        fil_content = b"update test file \x00 having binary content \x01\x02\x03\xff"
        reg_stamp = now_stamp()

        try:
            write_file(reg_path, b"")
            oai_obj = mocked_client.register_file(reg_name, root_path=reg_root, stamp=reg_stamp)
            assert mocked_client.error_message == ""
            assert oai_obj is not None
            assert mocked_client.o_synchronize_with_server_if_online()
            assert _csh_file_content(mocked_client, oai_obj) == {reg_name: b""}
            oaio_id = oai_obj.oaio_id

            write_file(upd_path, fil_content, make_dirs=True)
            upd_stamp = now_stamp()

            oai_obj = mocked_client.update_file(oaio_id, file_name=upd_name, root_path=upd_root, stamp=upd_stamp)
            assert mocked_client.o_synchronize_with_server_if_online()

            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert oai_obj.client_values[ROOT_VALUES_KEY] == upd_root
            assert oai_obj.server_values[ROOT_VALUES_KEY] == placeholder_path(reg_root)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == upd_name
            assert oai_obj.server_values[FILES_VALUES_KEY][0] == reg_name
            assert oai_obj.client_stamp == upd_stamp
            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(mocked_client.client_objectz) == 1
            assert oaio_id in mocked_client.client_objectz

            assert os_path_isfile(reg_path)
            assert os_path_isfile(upd_path)
            assert _csh_file_content(mocked_client, oai_obj) == {upd_name: fil_content}

        finally:
            if oai_obj:
                assert mocked_client.unregister_object(oai_obj.oaio_id) == "", "ERR:" + mocked_client.error_message
                assert _csh_file_remove(mocked_client, oai_obj) == ""
                assert _csh_mock_cleared_errors() == ""
                assert len(mocked_client.client_objectz) == 0
            if os_path_isdir(reg_root):
                shutil.rmtree(reg_root)
            if os_path_isdir(upd_root):
                shutil.rmtree(upd_root)

    def test_update_folder(self, mocked_client):
        # noinspection PyTypeChecker
        root_path = os_path_abspath(os_path_join(mocked_client.client_root, FILES_DIR))
        sub_dirs = ['sub_dir1', 'sub_dir3/sub sub_dir']
        file_paths = ['tEst file.tst',
                      os_path_join(sub_dirs[0], 'tst sub1-fil.tst'),
                      os_path_join(sub_dirs[1], 'tst_sub3_sub_fil.tst'),
                      ]
        fil_content = b"update folder test file \x00 binary content \x01\x02\x03\xff"

        assert mocked_client.o_synchronize_with_server_if_online()
        local_object_count = len(mocked_client.client_objectz)
        csh_api = mocked_client._csh_api(mocked_client.csh_default_id)
        oai_obj = None
        oaio_id = ""

        try:
            reg_stamp = now_stamp()
            for dir_nam in sub_dirs:
                os.makedirs(os_path_join(root_path, dir_nam))
            oai_obj = mocked_client.register_folder(root_path, stamp=reg_stamp)
            assert mocked_client.o_synchronize_with_server_if_online()
            assert mocked_client.error_message == ""
            assert len(mocked_client.client_objectz[oai_obj.oaio_id].client_values[FILES_VALUES_KEY]) == 0
            oaio_id = oai_obj.oaio_id

            upd_stamp = now_stamp()
            for fil_nam in file_paths:
                write_file(os_path_join(root_path, fil_nam), fil_content + fil_nam.encode())

            oai_obj = mocked_client.update_folder(oai_obj.oaio_id, root_path=root_path, stamp=upd_stamp)

            assert mocked_client.error_message == ""
            assert oai_obj.oaio_id in mocked_client.client_objectz
            assert oai_obj is mocked_client.client_objectz[oai_obj.oaio_id]
            assert oai_obj.client_stamp == upd_stamp
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(root_path, fil_nam)))
                srv_fil = os_path_join(oaio_id, upd_stamp, fil_nam)
                assert csh_api.deployed_file_content(srv_fil) is None
            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.server_values.get(FILES_VALUES_KEY) == []

            assert mocked_client.o_synchronize_with_server_if_online()

            assert mocked_client.error_message == ""
            assert oai_obj.oaio_id in mocked_client.client_objectz
            assert oai_obj.client_stamp == upd_stamp
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(root_path, fil_nam)))
                srv_fil = os_path_join(oaio_id, upd_stamp, fil_nam)
                assert csh_api.deployed_file_content(srv_fil) == fil_content + fil_nam.encode()

            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.server_values.get(FILES_VALUES_KEY) == []

        finally:
            err_msg = "ERR:" + mocked_client.error_message
            if oaio_id:
                assert mocked_client.unregister_object(oaio_id, wipe_files=True) == "", err_msg
                assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))
                assert len(mocked_client.client_objectz) == local_object_count, err_msg

    def test_update_object_after_upload(self, mocked_client):
        oai_obj = None
        try:
            reg_stamp = now_stamp()
            oai_obj = mocked_client.register_object({'val_key': 'reg_val'}, stamp=reg_stamp)
            assert mocked_client.o_synchronize_with_server_if_online()
            upd_stamp = now_stamp()

            mocked_client.update_object(oai_obj.oaio_id, {'val_key': 'upd_val'}, stamp=upd_stamp)

            assert oai_obj.oaio_id in mocked_client.client_objectz
            assert mocked_client.client_objectz[oai_obj.oaio_id].client_stamp == upd_stamp
            assert mocked_client.client_objectz[oai_obj.oaio_id].client_values['val_key'] == 'upd_val'

            assert mocked_client.client_objectz[oai_obj.oaio_id].server_stamp == reg_stamp
            assert mocked_client.client_objectz[oai_obj.oaio_id].server_values.get('val_key') == 'reg_val'

        finally:
            if oai_obj:
                assert mocked_client.unregister_object(oai_obj.oaio_id, wipe_files=True) == ""
                assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_update_object_before_upload(self, mocked_client):
        oai_obj = None
        try:
            reg_stamp = now_stamp()
            oai_obj = mocked_client.register_object({'val_key': 'reg_val'}, stamp=reg_stamp)
            upd_stamp = now_stamp()

            mocked_client.update_object(oai_obj.oaio_id, {'val_key': 'upd_val'}, stamp=upd_stamp)

            assert oai_obj.oaio_id in mocked_client.client_objectz
            assert mocked_client.client_objectz[oai_obj.oaio_id].client_stamp == upd_stamp
            assert mocked_client.client_objectz[oai_obj.oaio_id].client_values['val_key'] == 'upd_val'

            assert not mocked_client.client_objectz[oai_obj.oaio_id].server_stamp
            assert not mocked_client.client_objectz[oai_obj.oaio_id].server_values

        finally:
            if oai_obj:
                assert mocked_client.unregister_object(oai_obj.oaio_id, wipe_files=True) == ""
                assert not os_path_isfile(os_path_join(mocked_client.client_root, OBJECTS_DIR, oai_obj.oaio_id))

    def test_upsert_subscription(self, mocked_client):
        oai_obj = mocked_client.register_object({})

        assert oai_obj
        assert oai_obj.oaio_id in mocked_client.client_objectz
        assert oai_obj.username == mocked_client.user_name
        assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

        pid = 0
        try:
            pid = mocked_client.upsert_subscription(oai_obj.oaio_id, other_user, access_right=UPDATE_ACCESS_RIGHT)
            assert mocked_client.error_message == ""
            assert pid != 0

            mocked_client.user_name = other_user
            mocked_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())
            assert oai_obj.oaio_id in mocked_client.client_objectz

        finally:
            if pid:
                mocked_client.user_name = oai_obj.username
                mocked_client.session.headers[HTTP_HEADER_USR_ID] = repr(oai_obj.username.encode())
                assert mocked_client.unsubscribe(oai_obj.oaio_id, other_user) == ""
                assert oai_obj.oaio_id in mocked_client.client_objectz

                mocked_client.user_name = other_user
                mocked_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())

    def test_upsert_subscription_err(self, mocked_client):
        oai_obj = mocked_client.register_object({})
        mocked_client.session.post.side_effect = _mocked_get_or_post_failure_response

        pid = mocked_client.upsert_subscription(oai_obj.oaio_id, other_user, access_right=UPDATE_ACCESS_RIGHT)

        assert pid == 0
        assert oai_obj.oaio_id in mocked_client.error_message
        assert other_user in mocked_client.error_message

    def test_userz_access(self, mocked_client):
        users = mocked_client.userz_access('any_id_because_only_checking_for_correct_user_name')
        assert isinstance(users, list)
        assert len(users) == 1
        assert users[0]['username'] == 'mocked_username'

    def test_userz_access_err(self, mocked_client):
        mocked_client.session.post.side_effect = _mocked_get_or_post_failure_response
        users = mocked_client.userz_access('any_id_because_only_checking_for_correct_user_name')
        assert isinstance(users, list)
        assert len(users) == 0

    def test_wipe_user(self, mocked_client):
        oai_obj = None
        try:
            oai_obj = mocked_client.register_object({})
            mocked_client.upsert_subscription(oai_obj.oaio_id, other_user)  # create User/Userz recs for other usr

            assert mocked_client.wipe_user(other_user) == ""

        finally:
            if oai_obj:
                assert mocked_client.unregister_object(oai_obj.oaio_id) == ""


# ******   integration test against live cloud storage and oaio servers   ******


@pytest.fixture(scope="session")
def live_client():
    """ on local machine connect to personal server in order to do integration tests """
    storage_root = 'liTstOC_sto_root'
    client_root = os_path_join(TESTS_FOLDER, 'liTstOC_cli_root')
    assert not os_path_isdir(client_root)

    liv_api = ocl = None
    try:
        liv_api = DigiApi(root_folder=storage_root,     # TEST_DIGI_ROOT_FOLDER_PATH exclusive to test_cloud_storage.py
                          email=os.environ.get('TEST_DIGI_API_EMAIL'),
                          password=os.environ.get('TEST_DIGI_API_PASSWORD'))
        ocl = OaioClient(os.environ['OAIO_HOST_NAME'],
                         {'username': os.environ['OAIO_USERNAME'], 'password': os.environ['OAIO_PASSWORD']},
                         app_id='OCLITst',              # Oaio Client Live Integration Tests with individual app id
                         device_id='dIi',
                         csh_default_id='_TstCshLive',  # actually not needed because _csh_api() get monkey patched
                         client_root=client_root,
                         )
        ocl.o_synchronize_with_server_if_online = ocl.synchronize_with_server_if_online
        ocl.synchronize_with_server_if_online = lambda: True  # monkey patch to allow manual server sync in tests
        ocl._csh_api = lambda *_args: liv_api           # monkey patch to prevent Cshz test rec in live server database

        assert ocl.error_message == ""
        assert liv_api.error_message == ""
        # noinspection PyTypeChecker
        assert not os.listdir(local_obj_cache_path := os_path_join(ocl.client_root, OBJECTS_DIR))
        # noinspection PyProtectedMember
        assert not ocl._load_server_objectz()           # ensure empty/clean test env
        assert other_user not in [_['username'] for _ in ocl.userz_access('any_not_existing_oaio_id')]
        assert liv_api.list_dir('/') == []              # None if storage_root dir does not exist, [] if dir is empty

        yield cast(Any, ocl)

        # noinspection PyTypeChecker
        assert not os.listdir(local_obj_cache_path)
        # noinspection PyProtectedMember
        assert not ocl._load_server_objectz()  # ensure empty/clean test env
        assert other_user not in [_['username'] for _ in ocl.userz_access('any_existing_or_not_existing_oaio_id')]
        assert liv_api.list_dir('/') == []              # None if storage_root dir does not exist, [] if dir is empty

    finally:    # cleanup - also after failed test
        if ocl:
            # noinspection PyProtectedMember
            for oai_obj in ocl._load_server_objectz().values():
                # noinspection PyProtectedMember
                ocl._delete_server_object(oai_obj)
            if other_user in [_['username'] for _ in ocl.userz_access('any_NOT_existing_oaio_id')]:
                ocl.wipe_user(other_user)
        if ocl.error_message:
            print(f"live test oaio server cleanup errors: \n{ocl.error_message}")

        if liv_api and (liv_api.delete_file_or_folder('/') or liv_api.list_dir('/') is not None):
            print(f"live test storage server {storage_root=} cleanup errors: \n{liv_api.error_message}")

        if os_path_isdir(client_root):
            shutil.rmtree(client_root)


@pytest.mark.skipif("not os.environ.get('OAIO_HOST_NAME')", reason="disable tests on gitlab CI or if servers are down")
class TestIntegrationWithLiveServers:
    """ integration tests running only on local machine, using your private oaio and cloud storage live servers. """
    def test_connect(self, live_client):
        assert live_client.error_message == ""
        assert live_client.connected

        assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
        assert live_client.connected

    def test_last_sync_stamp(self, live_client):
        assert live_client.last_sync_stamp
        stamp = now_stamp()
        live_client.last_sync_stamp = stamp
        assert live_client.last_sync_stamp == stamp

    def test_register_file(self, live_client):
        oai_obj = None
        stamp = now_stamp()
        dir_path = ""
        fil_name = 'tst_fil.yyy'
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"

        assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
        local_object_count = len(live_client.client_objectz)

        try:
            oai_obj = live_client.register_file(fil_name, file_content=fil_content, stamp=stamp)

            oaio_id = oai_obj.oaio_id
            dir_path = live_client._client_file_root(oaio_id, oai_obj.client_values)
            assert live_client.error_message == ""
            assert oai_obj is not None
            assert oaio_id
            assert oai_obj.csh_id

            assert ROOT_VALUES_KEY not in oai_obj.client_values
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert os_path_isfile(os_path_join(dir_path, fil_name))
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(live_client.client_objectz) == local_object_count + 1
            assert oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oaio_id] == oai_obj

            assert _csh_file_content(live_client, oai_obj) == {fil_name: None}

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
            assert _csh_file_content(live_client, oai_obj) == {fil_name: fil_content}

        finally:
            if oai_obj:
                assert _csh_file_remove(live_client, oai_obj) == ""
                assert live_client.unregister_object(oai_obj.oaio_id) == ""
                assert len(live_client.client_objectz) == local_object_count
            if os_path_isdir(dir_path):
                shutil.rmtree(dir_path)

    def test_register_file_with_root(self, live_client):
        oai_obj = None
        stamp = now_stamp()
        dir_path = os_path_abspath(os_path_join(TESTS_FOLDER, 'reg file dir'))
        fil_name = 'tst_fil.tst'
        fil_path = os_path_join(dir_path, fil_name)
        fil_content = b"test file \x00 having binary content \x01\x02\x03\xff"

        local_object_count = len(live_client.client_objectz)

        try:
            write_file(fil_path, fil_content, make_dirs=True)

            oai_obj = live_client.register_file(fil_name, root_path=dir_path, stamp=stamp)
            assert live_client.error_message == ""
            assert oai_obj is not None

            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == dir_path
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(live_client.client_objectz) == local_object_count + 1
            assert oai_obj.oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oai_obj.oaio_id] == oai_obj

            assert os_path_isfile(fil_path)
            assert _csh_file_content(live_client, oai_obj) == {fil_name: None}

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
            assert _csh_file_content(live_client, oai_obj) == {fil_name: fil_content}

        finally:
            try:
                if oai_obj:
                    assert _csh_file_remove(live_client, oai_obj) == ""
                    assert live_client.unregister_object(oai_obj.oaio_id) == ""
                    assert len(live_client.client_objectz) == local_object_count
            finally:
                if os_path_isdir(dir_path):
                    shutil.rmtree(dir_path)

    def test_register_folder_with_root(self, live_client):
        stamp = now_stamp()
        folder_path = os_path_abspath(os_path_join(TESTS_FOLDER, 'folder_root'))
        sub_dirs = ['sub_dir1', 'sub_dir3/sub_sub_dir']
        file_paths = ['tst_fil.tst',
                      os_path_join(sub_dirs[0], 'tst_sub1_fil.tst'),
                      os_path_join(sub_dirs[1], 'tst_sub3_sub_fil.tst'),
                      ]
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"

        local_object_count = len(live_client.client_objectz)
        csh_api = live_client._csh_api(live_client.csh_default_id)
        oai_obj = None
        oaio_id = ""

        try:
            for fil_nam in file_paths:
                write_file(os_path_join(folder_path, fil_nam), fil_content + fil_nam.encode(), make_dirs=True)

            oai_obj = live_client.register_folder(folder_path, stamp=stamp)
            oaio_id = oai_obj.oaio_id

            assert oai_obj is not None
            assert oai_obj.oaio_id
            assert live_client.error_message == ""
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == normalize(folder_path)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            svr_path = os_path_join(oaio_id, stamp)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(folder_path, fil_nam)))
                assert csh_api.deployed_file_content(os_path_join(svr_path, fil_nam)) is None
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert not oai_obj.server_values
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1
            assert oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oaio_id] == oai_obj

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            assert live_client.error_message == ""
            oai_obj = live_client.client_objectz.get(oai_obj.oaio_id)
            assert oai_obj
            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == normalize(folder_path)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            svr_path = os_path_join(oaio_id, stamp)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(folder_path, fil_nam)))
                assert csh_api.deployed_file_content(os_path_join(svr_path, fil_nam)) == fil_content + fil_nam.encode()
            assert oai_obj.client_stamp == stamp
            assert oai_obj.server_stamp == stamp
            assert oai_obj.server_values == oai_obj.client_values
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1

        finally:
            if oaio_id:
                assert live_client.unregister_object(oaio_id, wipe_files=True) == ""
                assert len(live_client.client_objectz) == local_object_count
                err_msg = _csh_file_remove(live_client, oai_obj, file_count=len(file_paths))
                assert stamp in err_msg
                assert oaio_id in err_msg
            if os_path_isdir(folder_path):
                shutil.rmtree(folder_path)

    def test_register_object(self, live_client):
        oai_obj = None
        stamp = now_stamp()
        values = {'tst_str': 'tst_val', 'tst_int': 69}

        local_object_count = len(live_client.client_objectz)

        try:
            oai_obj = live_client.register_object(values, stamp=stamp)
            assert live_client.error_message == ""
            assert oai_obj is not None

            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert oai_obj.client_values == values
            assert not oai_obj.server_values
            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1
            assert oai_obj.oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oai_obj.oaio_id] == oai_obj

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            assert live_client.error_message == ""
            oai_obj = live_client.client_objectz.get(oai_obj.oaio_id)
            assert oai_obj
            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert oai_obj.client_values == values
            assert oai_obj.server_values == values
            assert oai_obj.client_stamp == stamp
            assert oai_obj.server_stamp == stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1

        finally:
            if oai_obj:
                assert live_client.unregister_object(oai_obj.oaio_id) == ""
                assert len(live_client.client_objectz) == local_object_count

    def test_synchronize_with_server_if_online(self, live_client):
        assert live_client.o_synchronize_with_server_if_online() is True, f"{live_client.error_message=}"

    def test_unregister_object(self, live_client):
        oai_obj = live_client.register_object({})
        assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

        assert oai_obj
        assert oai_obj.oaio_id in live_client._load_server_objectz()
        assert oai_obj.oaio_id in live_client.client_objectz
        assert oai_obj.username == live_client.user_name
        assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

        pid = 0
        try:
            pid = live_client.upsert_subscription(oai_obj.oaio_id, other_user, access_right=UPDATE_ACCESS_RIGHT)
            assert live_client.error_message == ""
            assert pid != 0

            # to allow check the subscription of other user and to mock a request, OAIO_USERNAME has to be supervisor
            live_client.user_name = other_user
            live_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())
            assert oai_obj.oaio_id in live_client._load_server_objectz(), f"{live_client.error_message=}"

        finally:
            if pid:
                live_client.user_name = oai_obj.username
                live_client.session.headers[HTTP_HEADER_USR_ID] = repr(oai_obj.username.encode())
                assert live_client.unsubscribe(oai_obj.oaio_id, other_user) == ""
                assert oai_obj.oaio_id in live_client._load_server_objectz(), f"{live_client.error_message=}"

                live_client.user_name = other_user
                live_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())
                assert oai_obj.oaio_id not in live_client._load_server_objectz()

                live_client.user_name = oai_obj.username
                live_client.session.headers[HTTP_HEADER_USR_ID] = repr(oai_obj.username.encode())
                assert live_client.unsubscribe(oai_obj.oaio_id, oai_obj.username)   # creator subscription not deletable
                assert live_client.unregister_object(oai_obj.oaio_id) == ""
                assert oai_obj.oaio_id not in live_client._load_server_objectz(), f"{live_client.error_message=}"

    def test_unsubscribe(self, live_client):
        oai_obj = None
        try:
            oai_obj = live_client.register_object({})
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
            assert live_client.upsert_subscription(oai_obj.oaio_id, other_user)

            assert oai_obj
            assert oai_obj.oaio_id in live_client._load_server_objectz()
            assert oai_obj.oaio_id in live_client.client_objectz

            assert live_client.unsubscribe(oai_obj.oaio_id, other_user) == ""

            live_client.user_name = other_user
            live_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())
            assert oai_obj.oaio_id not in live_client._load_server_objectz()

            live_client.user_name = oai_obj.username
            live_client.session.headers[HTTP_HEADER_USR_ID] = repr(oai_obj.username.encode())
            assert oai_obj.oaio_id in live_client._load_server_objectz()
            assert oai_obj.oaio_id in live_client.client_objectz

        finally:
            if oai_obj:
                assert live_client.unregister_object(oai_obj.oaio_id) == ""

    def test_unsubscribe_err(self, live_client):
        oai_obj = None
        try:
            oai_obj = live_client.register_object({})
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
            assert oai_obj
            assert oai_obj.oaio_id in live_client._load_server_objectz()
            assert oai_obj.oaio_id in live_client.client_objectz

            err_msg = live_client.unsubscribe(oai_obj.oaio_id, oai_obj.username)  # ERR: creator has to unregister

            assert oai_obj.oaio_id in err_msg
            assert oai_obj.username in err_msg
            assert oai_obj.oaio_id in live_client._load_server_objectz()
            assert oai_obj.oaio_id in live_client.client_objectz

        finally:
            if oai_obj:
                assert live_client.unregister_object(oai_obj.oaio_id) == ""
            assert oai_obj.oaio_id not in live_client._load_server_objectz()
            assert oai_obj.oaio_id not in live_client.client_objectz

    def test_update_file(self, live_client):
        reg_stamp = now_stamp()
        fil_name = 'tst_fil.zzz'
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"
        local_object_count = len(live_client.client_objectz)
        dir_path = ""
        try:
            reg_obj = live_client.register_file(fil_name, file_content=b"", stamp=reg_stamp)
            oaio_id = reg_obj.oaio_id
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            upd_stamp = now_stamp()
            oai_obj = live_client.update_file(oaio_id, file_name=fil_name, file_content=fil_content, stamp=upd_stamp)

            assert oai_obj is not None
            assert oai_obj.oaio_id == oaio_id
            dir_path = live_client._client_file_root(oaio_id, oai_obj.client_values)
            assert live_client.error_message == ""

            assert ROOT_VALUES_KEY not in oai_obj.client_values
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == 1
            assert oai_obj.client_values[FILES_VALUES_KEY][0] == fil_name
            assert os_path_isfile(os_path_join(dir_path, fil_name))
            assert oai_obj.server_values == oai_obj.client_values
            assert oai_obj.client_stamp == upd_stamp
            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            assert len(live_client.client_objectz) == local_object_count + 1
            assert oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oaio_id] == oai_obj

            assert _csh_file_content(live_client, oai_obj) == {fil_name: None}

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            assert _csh_file_content(live_client, oai_obj) == {fil_name: fil_content}

            assert _csh_file_remove(live_client, oai_obj) == ""
            assert live_client.unregister_object(oai_obj.oaio_id) == ""

        finally:
            if dir_path and os_path_isdir(dir_path):
                shutil.rmtree(dir_path)

    def test_update_folder_with_root(self, live_client):
        reg_stamp = now_stamp()
        folder_path = os_path_abspath(os_path_join(TESTS_FOLDER, 'fol_upd_root'))
        sub_dirs = ['sub_dir1', 'sub_dir3/sub_sub_dir']
        file_paths = ['tst_fil.tst',
                      os_path_join(sub_dirs[0], 'tst_sub1_fil.tst'),
                      os_path_join(sub_dirs[1], 'tst_sub3_sub_fil.tst'),
                      ]
        fil_content = b"test file \x00 binary content \x01\x02\x03\xff"
        local_object_count = len(live_client.client_objectz)
        oaio_id = ""
        oai_obj = None
        try:
            csh_api = live_client._csh_api(live_client.csh_default_id)
            for fil_nam in file_paths:
                write_file(os_path_join(folder_path, fil_nam), fil_content + fil_nam.encode(), make_dirs=True)
            reg_obj = live_client.register_folder(folder_path, stamp=reg_stamp)
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            upd_stamp = now_stamp()
            for fil_nam in file_paths:
                write_file(os_path_join(folder_path, fil_nam), fil_nam.encode() + b"-updated")
            oai_obj = live_client.update_folder(reg_obj.oaio_id, root_path=folder_path, stamp=upd_stamp)

            oaio_id = oai_obj.oaio_id
            assert oai_obj is not None
            assert oai_obj.oaio_id
            assert live_client.error_message == ""
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == normalize(folder_path)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            svr_path = os_path_join(oaio_id, upd_stamp)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(folder_path, fil_nam)))
                assert csh_api.deployed_file_content(os_path_join(svr_path, fil_nam)) is None
            assert oai_obj.client_stamp == upd_stamp
            assert oai_obj.server_stamp == reg_stamp
            assert oai_obj.server_values == oai_obj.client_values
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1
            assert oaio_id in live_client.client_objectz
            assert live_client.client_objectz[oaio_id] == oai_obj

            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            assert live_client.error_message == ""
            oai_obj = live_client.client_objectz.get(oai_obj.oaio_id)
            assert oai_obj
            assert oai_obj.oaio_id
            assert oai_obj.csh_id
            assert ROOT_VALUES_KEY in oai_obj.client_values
            assert normalize(oai_obj.client_values[ROOT_VALUES_KEY]) == normalize(folder_path)
            assert FILES_VALUES_KEY in oai_obj.client_values
            assert len(oai_obj.client_values[FILES_VALUES_KEY]) == len(file_paths)
            svr_path = os_path_join(oaio_id, upd_stamp)
            for fil_nam in file_paths:
                assert fil_nam in oai_obj.client_values[FILES_VALUES_KEY]
                assert os_path_isfile(normalize(os_path_join(folder_path, fil_nam)))
                assert csh_api.deployed_file_content(os_path_join(svr_path, fil_nam)) == fil_nam.encode() + b"-updated"
            assert oai_obj.client_stamp == upd_stamp
            assert oai_obj.server_stamp == upd_stamp, f"reg={reg_stamp} upd={upd_stamp}"
            assert oai_obj.server_values == oai_obj.client_values
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
            assert len(live_client.client_objectz) == local_object_count + 1

        finally:    # cleanup
            try:
                if oaio_id:
                    assert live_client.unregister_object(oaio_id, wipe_files=True) == ""
                    assert len(live_client.client_objectz) == local_object_count
                    err_msg = _csh_file_remove(live_client, oai_obj, file_count=len(file_paths))
                    assert reg_stamp in err_msg
                    assert oaio_id in err_msg
            finally:
                if os_path_isdir(folder_path):
                    shutil.rmtree(folder_path)

    def test_update_object(self, live_client):
        reg_stamp = now_stamp()
        reg_values = {'tst_str': 'tst_val', 'tst_int': 69}
        local_object_count = len(live_client.client_objectz)
        oai_obj = live_client.register_object(reg_values, stamp=reg_stamp)

        upd_values = {'tst_str': '_val', 'tst_int': 369}
        upd_stamp = now_stamp()
        oai_obj = live_client.update_object(oai_obj.oaio_id, upd_values, stamp=upd_stamp)
        assert live_client.error_message == ""
        assert oai_obj is not None

        assert oai_obj.oaio_id
        assert oai_obj.csh_id
        assert oai_obj.client_values == upd_values
        assert not oai_obj.server_values
        assert oai_obj.client_stamp == upd_stamp
        assert not oai_obj.server_stamp
        assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
        assert len(live_client.client_objectz) == local_object_count + 1
        assert oai_obj.oaio_id in live_client.client_objectz
        assert live_client.client_objectz[oai_obj.oaio_id] == oai_obj

        assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

        assert live_client.error_message == ""
        oai_obj = live_client.client_objectz.get(oai_obj.oaio_id)
        assert oai_obj
        assert oai_obj.oaio_id
        assert oai_obj.csh_id
        assert oai_obj.client_values == upd_values
        assert oai_obj.server_values == upd_values
        assert oai_obj.client_stamp == upd_stamp
        assert oai_obj.server_stamp == upd_stamp
        assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT
        assert len(live_client.client_objectz) == local_object_count + 1

        if oai_obj:
            assert live_client.unregister_object(oai_obj.oaio_id) == ""
            assert len(live_client.client_objectz) == local_object_count

    def test_upsert_subscription(self, live_client):
        oai_obj = None
        pid = 0
        try:
            oai_obj = live_client.register_object({})
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"

            assert oai_obj
            assert oai_obj.oaio_id in live_client._load_server_objectz()
            assert oai_obj.oaio_id in live_client.client_objectz
            assert oai_obj.username == live_client.user_name
            assert oai_obj.csh_access_right == CREATE_ACCESS_RIGHT

            pid = live_client.upsert_subscription(oai_obj.oaio_id, other_user, access_right=UPDATE_ACCESS_RIGHT)
            assert live_client.error_message == ""
            assert pid != 0

            # to allow check the subscription of other user and to mock a request, OAIO_USERNAME has to be supervisor
            live_client.user_name = other_user
            live_client.session.headers[HTTP_HEADER_USR_ID] = repr(other_user.encode())
            assert oai_obj.oaio_id in live_client._load_server_objectz(), f"{live_client.error_message=}"

        finally:
            if pid:
                live_client.user_name = oai_obj.username
                live_client.session.headers[HTTP_HEADER_USR_ID] = repr(oai_obj.username.encode())
                assert live_client.wipe_user(other_user) == ""
            if oai_obj:
                assert live_client.unregister_object(oai_obj.oaio_id) == ""

    def test_userz_access(self, live_client):
        users = live_client.userz_access("any-id")
        assert isinstance(users, list)
        assert len(users) >= 1
        assert isinstance(users[0], dict)
        assert 'username' in users[0]
        assert 'access_right' in users[0]

    def test_wipe_user(self, live_client):
        oai_obj = None
        try:
            oai_obj = live_client.register_object({})
            assert live_client.o_synchronize_with_server_if_online(), f"{live_client.error_message=}"
            assert live_client.upsert_subscription(oai_obj.oaio_id, other_user)  # create User/Userz recs for other user
            assert other_user in [_['username'] for _ in live_client.userz_access(oai_obj.oaio_id)]

            assert live_client.wipe_user(other_user) == ""
            assert other_user not in [_['username'] for _ in live_client.userz_access(oai_obj.oaio_id)]

        finally:
            if oai_obj:
                assert live_client.unregister_object(oai_obj.oaio_id) == ""

    def test_teardown(self):
        """ last live test method, to display teardown errors of live_client fixture (with session scope) separately """
