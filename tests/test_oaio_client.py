""" unit/integration tests of the oaio client package. """
import os
import pytest

from conftest import skip_gitlab_ci

from ae.base import load_dotenvs                                                # type: ignore
from ae.oaio_model import CREATE_WRITE_ACCESS, now_stamp
from ae.paths import normalize

from ae.oaio_client import OaioClient


load_dotenvs()


@pytest.fixture
def client():
    """ connect on local machine to do integration tests """
    ocl = OaioClient(os.environ['OAIO_HOST_NAME'],
                     {'username': os.environ['OAIO_USERNAME'], 'password': os.environ['OAIO_PASSWORD']},
                     )
    yield ocl


class TestInstantiation:
    def test_invalid_host_credentials(self):
        ocl = OaioClient("", {})
        assert ocl
        assert not ocl.synchronize_with_server_if_online()

    def test_defaults(self):
        ocl = OaioClient("", {})
        assert ocl.app_id
        assert ocl.device_id
        assert ocl.cdn_default_id == 'Digi'
        assert ocl.local_root_path == normalize("{ado}/oaio_root/")


@skip_gitlab_ci
class TestClient:
    def test_connect(self, client):
        assert client.connected

    def test_register_obj(self, client):
        oai_obj = None
        stamp = now_stamp()
        try:
            oai_obj = client.register_object({'tst_str': 'tst_val', 'tst_int': 69}, stamp=stamp)
            assert client.error_message == ""
            assert oai_obj is not None

            assert oai_obj.oaio_id
            assert oai_obj.cdn_id

            assert oai_obj.client_values
            assert not oai_obj.server_values

            assert oai_obj.client_stamp == stamp
            assert not oai_obj.server_stamp

            assert oai_obj.cdn_write_access == CREATE_WRITE_ACCESS

        finally:
            if oai_obj:
                assert client.unregister_object(oai_obj.oaio_id)
