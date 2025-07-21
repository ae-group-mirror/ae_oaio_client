# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.tpl_project V0.3.36
# pylint: disable=redefined-outer-name, unused-argument; suppress fixtures conflicts (silly pylint)
""" fixtures for to test this project """
import os
import sys
import glob
import pytest


SKIP_EXPRESSION = "'CI_PROJECT_ID' in os.environ"
skip_gitlab_ci = pytest.mark.skipif(SKIP_EXPRESSION, reason="incomplete development environment and headless gitlab CI")


@pytest.fixture
def tst_app_key():
    """ provide value used in tests for AppBase.app_key. """
    return 'pyTstConsAppKey'


@pytest.fixture
def sys_argv_app_key_restore(tst_app_key):          # needed for tests using sys.argv/get_opt() of ConsoleApp
    """ change sys.argv before test run to use test app key and restore sys.argv after test run. """
    old_argv = sys.argv
    sys.argv = [tst_app_key, ]

    yield tst_app_key

    sys.argv = old_argv


@pytest.fixture
def restore_app_env(sys_argv_app_key_restore):
    """ restore app environment after test run - needed for tests instantiating AppBase/ConsoleApp. """
    # LOCAL IMPORT because a portion may not depend-on/use ae.core
    # noinspection PyProtectedMember
    # pylint: disable=import-outside-toplevel
    from ae.core import app_inst_lock, _APP_INSTANCES, _unregister_app_instance     # type: ignore

    yield sys_argv_app_key_restore

    # added outer list because unregister does _APP_INSTANCES.pop() calls
    # and added inner list because the .keys() 'generator' object is not reversible
    with app_inst_lock:
        app_keys = list(_APP_INSTANCES.keys())[::-1]
        for key in app_keys:
            # copied from ae.enaml_app conftest.py (not needed for apps based on ae.kivy)
            app_instance = _APP_INSTANCES[key]
            app_win = getattr(app_instance, 'framework_win', False)
            if app_win and hasattr(app_win, 'close') and callable(app_win.close):
                app_win.close()

            # remove app from ae.core app register/dict
            _unregister_app_instance(key)


@pytest.fixture
def cons_app(restore_app_env):
    """ provide ConsoleApp instance that will be unregistered automatically """
    # LOCAL IMPORT because some portions like e.g. ae_core does not depend/use ae.console
    from ae.console import ConsoleApp       # type: ignore # pylint: disable=import-outside-toplevel
    yield ConsoleApp()


@pytest.fixture
def tst_system(cons_app):
    """ CURRENTLY NOT USED """
    # pylint: disable=import-outside-toplevel, no-name-in-module, import-error
    from ae.sys_core import SystemBase      # type: ignore
    yield SystemBase('Tst', cons_app, dict(User='TstUsr', Password='TstPwd', Dsn='TstDb@TstHost'))


def delete_files(file_name, keep_ext=False, ret_type='count'):
    """ clean up test log files and other test files after test run. """
    if keep_ext:
        file_path, file_ext = os.path.splitext(file_name)
        file_mask = file_path + '*' + file_ext
    else:
        file_mask = file_name + '*'
    cnt = 0
    ret = []
    for fil_nam in glob.glob(file_mask):
        if ret_type == 'contents':
            with open(fil_nam) as file_handle:        # pylint: disable=unspecified-encoding
                file_content = file_handle.read()
            ret.append(file_content)
        elif ret_type == 'names':
            ret.append(fil_nam)
        os.remove(fil_nam)
        cnt += 1
    return cnt if ret_type == 'count' else ret
