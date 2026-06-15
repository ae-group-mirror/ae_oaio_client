# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.79
""" setup of ae namespace module portion oaio_client: Our Asynchronously Interchangeable Objects Client. """
import sys
# noinspection PyUnresolvedReferences
import pathlib
# noinspection PyUnresolvedReferences
import setuptools


print("SetUp " + __name__ + ": " + sys.executable + str(sys.argv) + f" {sys.path=}")

setup_kwargs = {
    'author': 'AndiEcker',
    'author_email': 'aecker2@gmail.com',
    'classifiers': [
        'Development Status :: 3 - Alpha',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Typing :: Typed',
    ],
    'description': 'ae namespace module portion oaio_client: Our Asynchronously Interchangeable Objects Client',
    'extras_require': {
        'dev': [
            'aedev_project_tpls',
            'ae_ae',
            'anybadge',
            'flake8',
            'mypy',
            'pylint',
            'pytest',
            'pytest-cov',
            'typing',
            'types-setuptools',
        ],
        'docs': [],
        'tests': [
            'anybadge',
            'flake8',
            'mypy',
            'pylint',
            'pytest',
            'pytest-cov',
            'typing',
            'types-setuptools',
        ],
    },
    'install_requires': [
        'ae_base',
        'ae_app_log',
        'ae_system',
        'ae_paths',
        'ae_cloud_storage',
        'ae_oaio_model',
        'requests',
    ],
    'keywords': [
        'configuration',
        'development',
        'environment',
        'productivity',
    ],
    'license': 'GPL-3.0-or-later',
    'long_description': (pathlib.Path(__file__).parent / 'README.md').read_text(encoding='utf-8'),
    'long_description_content_type': 'text/markdown',
    'name': 'ae_oaio_client',
    'package_data': {
        '': [],
    },
    'packages': [
        'ae',
    ],
    'project_urls': {
        'Bug Tracker': 'https://gitlab.com/ae-group/ae_oaio_client/-/issues',
        'Documentation': 'https://ae.readthedocs.io/en/latest/_autosummary/ae.oaio_client.html',
        'Repository': 'https://gitlab.com/ae-group/ae_oaio_client',
        'Source': 'https://ae.readthedocs.io/en/latest/_modules/ae/oaio_client.html',
    },
    'python_requires': '>=3.12',
    'url': 'https://gitlab.com/ae-group/ae_oaio_client',
    'version': '0.3.22',
    'zip_safe': True,
}

if __name__ == "__main__":
    setuptools.setup(**setup_kwargs)
    pass
