# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.tpl_project V0.3.36
""" setup of ae namespace module portion oaio_client: Our Asynchronously Interchangeable Objects Client. """



# noinspection PyUnresolvedReferences
import setuptools

setup_kwargs = {
    'author': 'AndiEcker',
    'author_email': 'aecker2@gmail.com',
    'classifiers': ['Development Status :: 3 - Alpha', 'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)', 'Natural Language :: English', 'Operating System :: OS Independent', 'Programming Language :: Python', 'Programming Language :: Python :: 3', 'Programming Language :: Python :: 3.9', 'Topic :: Software Development :: Libraries :: Python Modules'],
    'description': 'ae namespace module portion oaio_client: Our Asynchronously Interchangeable Objects Client',
    'extras_require': {'dev': ['aedev_tpl_project', 'ae_ae', 'anybadge', 'coverage-badge', 'aedev_git_repo_manager', 'flake8', 'mypy', 'pylint', 'pytest', 'pytest-cov', 'pytest-django', 'typing', 'types-setuptools', 'wheel', 'twine'], 'docs': [], 'tests': ['anybadge', 'coverage-badge', 'aedev_git_repo_manager', 'flake8', 'mypy', 'pylint', 'pytest', 'pytest-cov', 'pytest-django', 'typing', 'types-setuptools', 'wheel', 'twine']},
    'install_requires': ['ae_base', 'ae_cloud_storage', 'ae_oaio_model', 'ae_paths', 'requests'],
    'keywords': ['configuration', 'development', 'environment', 'productivity'],
    'license': 'OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
    'long_description': '<!-- THIS FILE IS EXCLUSIVELY MAINTAINED by the project ae.ae V0.3.96 -->\n<!-- THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.tpl_namespace_root V0.3.14 -->\n# oaio_client 0.3.19\n\n[![GitLab develop](https://img.shields.io/gitlab/pipeline/ae-group/ae_oaio_client/develop?logo=python)](\n    https://gitlab.com/ae-group/ae_oaio_client)\n[![LatestPyPIrelease](\n    https://img.shields.io/gitlab/pipeline/ae-group/ae_oaio_client/release0.3.18?logo=python)](\n    https://gitlab.com/ae-group/ae_oaio_client/-/tree/release0.3.18)\n[![PyPIVersions](https://img.shields.io/pypi/v/ae_oaio_client)](\n    https://pypi.org/project/ae-oaio-client/#history)\n\n>ae namespace module portion oaio_client: Our Asynchronously Interchangeable Objects Client.\n\n[![Coverage](https://ae-group.gitlab.io/ae_oaio_client/coverage.svg)](\n    https://ae-group.gitlab.io/ae_oaio_client/coverage/index.html)\n[![MyPyPrecision](https://ae-group.gitlab.io/ae_oaio_client/mypy.svg)](\n    https://ae-group.gitlab.io/ae_oaio_client/lineprecision.txt)\n[![PyLintScore](https://ae-group.gitlab.io/ae_oaio_client/pylint.svg)](\n    https://ae-group.gitlab.io/ae_oaio_client/pylint.log)\n\n[![PyPIImplementation](https://img.shields.io/pypi/implementation/ae_oaio_client)](\n    https://gitlab.com/ae-group/ae_oaio_client/)\n[![PyPIPyVersions](https://img.shields.io/pypi/pyversions/ae_oaio_client)](\n    https://gitlab.com/ae-group/ae_oaio_client/)\n[![PyPIWheel](https://img.shields.io/pypi/wheel/ae_oaio_client)](\n    https://gitlab.com/ae-group/ae_oaio_client/)\n[![PyPIFormat](https://img.shields.io/pypi/format/ae_oaio_client)](\n    https://pypi.org/project/ae-oaio-client/)\n[![PyPILicense](https://img.shields.io/pypi/l/ae_oaio_client)](\n    https://gitlab.com/ae-group/ae_oaio_client/-/blob/develop/LICENSE.md)\n[![PyPIStatus](https://img.shields.io/pypi/status/ae_oaio_client)](\n    https://libraries.io/pypi/ae-oaio-client)\n[![PyPIDownloads](https://img.shields.io/pypi/dm/ae_oaio_client)](\n    https://pypi.org/project/ae-oaio-client/#files)\n\n\n## installation\n\n\nexecute the following command to install the\nae.oaio_client module\nin the currently active virtual environment:\n \n```shell script\npip install ae-oaio-client\n```\n\nif you want to contribute to this portion then first fork\n[the ae_oaio_client repository at GitLab](\nhttps://gitlab.com/ae-group/ae_oaio_client "ae.oaio_client code repository").\nafter that pull it to your machine and finally execute the\nfollowing command in the root folder of this repository\n(ae_oaio_client):\n\n```shell script\npip install -e .[dev]\n```\n\nthe last command will install this module portion, along with the tools you need\nto develop and run tests or to extend the portion documentation. to contribute only to the unit tests or to the\ndocumentation of this portion, replace the setup extras key `dev` in the above command with `tests` or `docs`\nrespectively.\n\nmore detailed explanations on how to contribute to this project\n[are available here](\nhttps://gitlab.com/ae-group/ae_oaio_client/-/blob/develop/CONTRIBUTING.rst)\n\n\n## namespace portion documentation\n\ninformation on the features and usage of this portion are available at\n[ReadTheDocs](\nhttps://ae.readthedocs.io/en/latest/_autosummary/ae.oaio_client.html\n"ae_oaio_client documentation").\n',
    'long_description_content_type': 'text/markdown',
    'name': 'ae_oaio_client',
    'package_data': {'': []},
    'packages': ['ae'],
    'project_urls': {'Bug Tracker': 'https://gitlab.com/ae-group/ae_oaio_client/-/issues', 'Documentation': 'https://ae.readthedocs.io/en/latest/_autosummary/ae.oaio_client.html', 'Repository': 'https://gitlab.com/ae-group/ae_oaio_client', 'Source': 'https://ae.readthedocs.io/en/latest/_modules/ae/oaio_client.html'},
    'python_requires': '>=3.9',
    'setup_requires': ['aedev_setup_project'],
    'url': 'https://gitlab.com/ae-group/ae_oaio_client',
    'version': '0.3.19',
    'zip_safe': True,
}

if __name__ == "__main__":
    setuptools.setup(**setup_kwargs)
    pass
