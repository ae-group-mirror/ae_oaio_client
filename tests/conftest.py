# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.79
# pylint: disable=redefined-outer-name, unused-argument; suppress fixtures conflicts (silly pylint)
""" fixtures for to test this project """
import os
import sys
import glob
from inspect import getframeinfo
from typing import Any
from unittest.mock import patch

import pytest


# noinspection PyTypeChecker
assert (cwd := os.getcwd()) == (prj_root := os.path.dirname(os.path.dirname(__file__))), f"wrong {cwd=}, != {prj_root=}"
sys.path.insert(0, prj_root)  # add project root (==CWD) to sys.path (allowing to run pytest w/o the 'python -m' prefix)


SKIP_EXPRESSION = "'CI_PROJECT_ID' in os.environ"
skip_gitlab_ci = pytest.mark.skipif(SKIP_EXPRESSION, reason="incomplete development environment and headless gitlab CI")


# pytest hooks


# noinspection PyUnusedLocal
def pytest_collection_modifyitems(config, items):
    """ hook to convert pytest.mark.integration into a skip marker if env var RUN_INTEGRATION_TESTS is set. """
    if not os.getenv('RUN_INTEGRATION_TESTS'):
        skip_integration = pytest.mark.skip(reason="integration tests only if OS env var RUN_INTEGRATION_TESTS is true")
        for item in items:
            if 'integration' in item.keywords:
                item.add_marker(skip_integration)


def pytest_configure(config):
    """ pytest run configuration hook. """
    # define pytest.mark.integration as test class/method/function marker
    config.addinivalue_line("markers", "integration: mark integration test; activate via env var RUN_INTEGRATION_TESTS")
    # register xdist group marker to suppresses pytest warning if not installed (used e.g. in tests/test_integration.py)
    config.addinivalue_line("markers", "xdist_group(name): group tests for sequential execution if xdist is installed")


failed_items_node_ids = []                  #: stores the node ids of all the failed test items


# noinspection PyUnusedLocal
@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """ log all failed test items (e.g., for checks done in pytest_runtest_setup hook). """
    outcome = yield
    rep = outcome.get_result()
    if rep.failed:
        failed_items_node_ids.append(item.nodeid)


def pytest_runtest_setup(item):
    """ check if item is an integration test, and if yes then skip it, if a previous integration test failed. """
    path = item.nodeid.split('::')[0]
    if path == 'tests/test_integration.py' and path in [node_id.split('::')[0] for node_id in failed_items_node_ids]:
        pytest.skip(f"all the other integration tests due to the fail of '{failed_items_node_ids[-1]}'")


# fixtures and helpers


@pytest.fixture
def cons_app(restore_app_env):
    """ provide ConsoleApp instance that will be unregistered automatically """
    # LOCAL IMPORT because some portions like e.g. ae_core does not depend-on/use ae.console
    from ae.console import ConsoleApp       # type: ignore # pylint: disable=import-outside-toplevel
    yield ConsoleApp()


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


# log :meth:`as.console.ConsoleApp.shutdown` calls that are not patched via the func:`patched_shutdown_wrapper` fixture
LoggedShutdownCalls = list[tuple[int, str, list[str]]]
_logging_shutdown_patchers = []
_logged_shutdown_calls: LoggedShutdownCalls = []


def logging_unpatched_shutdown_setup():
    """ setup logging of unpatched calls of app.shutdown() for unit and integration tests.

    patching :meth:`ae.core.AppBase.shutdown` and :meth:`as.console.ConsoleApp.shutdown` to log calls that are not got
    patched by the func:`patched_shutdown_wrapper` fixture. preventing unregister of the main app instance and the
    template cache.
    """
    _logged_shutdown_calls.clear()
    _logging_shutdown_patchers.clear()
    _logging_shutdown_patchers.append(patch('ae.core.AppBase.shutdown', new=_log_shutdown_calls))
    _logging_shutdown_patchers.append(patch('ae.console.ConsoleApp.shutdown', new=_log_shutdown_calls))
    for patcher in _logging_shutdown_patchers:
        patcher.start()


def logging_unpatched_shutdown_teardown() -> LoggedShutdownCalls:
    """ teardown the patching&logging of app.shutdown() calls, setup by :func:`logging_unpatched_shutdown_setup`.

    :return:                    list of caught and logged shutdown calls or empty list if no shutdown got called. each
                                list item is a 3-item-tuple with (1) the shutdown error code, (2) the error message and
                                (3) a list of the error call stack trace lines.
    """
    for err, msg, trace in _logged_shutdown_calls:
        print(f" **** unpatched call of shutdown() detected with {err=} and {msg=}")
        for call_stack_entry in trace:
            print(f"    * {call_stack_entry}")
    for patcher in _logging_shutdown_patchers:
        patcher.stop()
    return _logged_shutdown_calls


def _log_shutdown_calls(main_app: Any, exit_code: int, error_message: str = ""):
    """ AppBase|ConsoleApp.shutdown()-mock to prevent unregister of main-app|template-projects to log them in tests. """
    from ae.system import stack_frames

    print()
    print(f"***** app.shutdown() called with {exit_code=} and {error_message=}; {main_app=}; stack:")
    trace = []
    for fra in stack_frames():
        inf = getframeinfo(fra)
        line = f"      File \"{inf.filename}\", line {inf.lineno}, in func={inf.function}: {inf.code_context}"
        print(line)     # print out stack trace line in the format so that PyCharm will create a link to the code line
        trace.append(line)
        if inf.function.startswith("test_"):
            break
    print()
    _logged_shutdown_calls.append((exit_code, error_message, trace))  # to be printed again by teardown_module()


@pytest.fixture
def patched_shutdown_wrapper():
    """ log :func:`ae.console.ConsoleApp.shutdown` function calls and args, while preventing exit/quit of main app. """
    exit_call_args = []

    class _ExitCaller(Exception):
        """ exception to recognize and simulate app shutdown for the code to be tested. """

    def _exit_(*args, **kwargs):
        # nonlocal exit_call_args
        if len(args) > 1:   # 1st arg is always the self/instance of the AppBase/ConsoleApp class
            kwargs['exit_code'] = args[1]
            if len(args) > 2:
                kwargs['error_message'] = args[2]
                if len(args) > 3:
                    kwargs['timeout'] = args[3]
                    if len(args) > 4:
                        kwargs['_unexpected_args_'] = args[4:]
        exit_call_args.append(kwargs)
        raise _ExitCaller("to be caught by the _call_wrapper() of the patched_shutdown_wrapper unit test fixture")

    def _call_wrapper(fun, *args, **kwargs):
        exit_call_args.clear()
        try:
            ret = fun(*args, **kwargs)
        except _ExitCaller:
            ret = None
        print(f"patched_shutdown_wrapper._call_wrapper {ret=}")
        return exit_call_args

    with (patch('ae.console.ConsoleApp.shutdown', new=_exit_),
          patch('ae.core.AppBase.shutdown', new=_exit_)):
        yield _call_wrapper


@pytest.fixture
def restore_app_env(sys_argv_app_key_restore):
    """ restore app environment after test run - needed for tests instantiating AppBase/ConsoleApp. """
    # LOCAL IMPORT because a portion may not depend-on/use ae.core
    # noinspection PyProtectedMember
    # pylint: disable=import-outside-toplevel
    from ae.core import _APP_INSTANCES, app_inst_lock, logger_shutdown, unregister_app_instance     # type: ignore

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
            unregister_app_instance(key)

        if not app_keys:    # else logger_shutdown got called already by unregister_app_instance()
            logger_shutdown()


@pytest.fixture
def sys_argv_app_key_restore(tst_app_key):          # needed for tests using sys.argv/get_option() of ConsoleApp
    """ change sys.argv before test run to use test app key and restore sys.argv after test run. """
    old_argv = sys.argv
    sys.argv = [tst_app_key, ]

    yield tst_app_key

    sys.argv = old_argv


@pytest.fixture
def tst_app_key():
    """ provide value used in tests for AppBase.app_key. """
    return 'pyTstConsAppKey'


@pytest.fixture
def tst_system(cons_app):
    """ CURRENTLY NOT USED """
    # pylint: disable=import-outside-toplevel, no-name-in-module, import-error
    from ae.sys_core import SystemBase      # type: ignore
    yield SystemBase('Tst', cons_app, dict(User='TstUsr', Password='Tst Pwd', Dsn='TstDb@TstHost'))
