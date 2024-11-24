
..
    THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.tpl_project V0.3.32

contributing
============

we want to make it as easy and fun as possible for you to contribute to this project.


reporting bugs
--------------

before you create a new issue, please check to see if you are using the latest version of this project; the bug may
already be resolved.

also search for similar problems in the issue tracker; it may already be an identified problem.

include as much information as possible into the issue description, at least:

1. version numbers (of Python and any involved packages).
2. small self-contained code example that reproduces the bug.
3. steps to reproduce the error.
4. any traceback/error/log messages shown.


requesting new features
-----------------------

1. on the git repository host server create new issue, providing a clear and detailed explanation of the feature
   you want and why it's important to add.
2. if you are able to implement the feature yourself (refer to the `contribution steps`_ section below).


contribution steps
------------------

thanks for your contribution -- we'll get your merge request reviewed. you could also review other merge requests, just
like other developers will review yours and comment on them. based on the comments, you should address them. once the
reviewers approve, the maintainers will merge.

before you start make sure you have a `GitLab account <https://gitlab.com/users/sign_up>`__.

contribution can be done either with the :mod:`git-repo-manager tool <aedev.git_repo_manager>` or directly by using
the ``git`` command and the ``Gitlab`` server.


using the git repository manager `grm`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. fork and clone the repository of this project to your computer

   in your console change the working directory to your project's parent folder. then run the following command with
   the ``new_feature_or_fix`` part replaced by an appropriate branch name, describing shortly your contribution::

      grm -b new_feature_or_fix fork ae-group/ae_oaio_client

   .. note::
      the ``grm fork`` action will also add the forked repository as the remote ``upstream`` to your local
      repository.

   after the repository fork you change your current working directory to the new working tree root folder,
   created by the ``grm fork`` action, and execute the ``grm renew`` action. this will prepare a new package version
   of the project and upgrade the project files created from templates to its latest version.

2. code and check

   now use your favorite IDE/Editor to implement the new feature or code the bug fix. don't forget to amend the project
   with new unit and integrity tests, and ensure they pass, by executing from time to time the
   ``grm check`` action.

3. publish your changes

   before you initiate a push/merge request against the Gitlab server, execute the ``grm prepare`` action,
   which will create, with the help of the ``git diff`` command, a `.commit_msg.txt` file in the
   working tree root of your project, containing a short summary in the first line followed with a blank line and
   a list of the project files that got added, changed or deleted.

   .. hint::
      the `.commit_msg.txt` file can be amended by any text editor before you run the ``grm commit`` action.
      for changes initiated by an issue please include the issue number (in the format ``fixes #<issue-number>``) into
      this file. you may use ``Markdown`` syntax in this file for simple styling.

   to finally commit and upload your changes run the following three grm actions in the root folder of your project::

      grm commit
      grm push
      grm request

   the ``grm commit`` command is first executing a ``grm check`` action to do a finally check of the project resources
   and to run the unit and integrity tests. if all these checks pass then a new git commit will be created, including
   your changes to the project. ``grm push``will then push the commit to your ``origin`` remote repository (your fork)
   and ``grm request`` will finally create a bew merge/pull request against the ``upstream`` remote repository
   (the forked one).

   .. hint::
      to complete the workflow a maintainer of the project has to execute the ``grm release`` action. this will
      merge your changes into the main branch `develop` of the ``upstream`` repository and then release
      a new version of the project onto PyPI.


more detailed information of the features of the ``grm`` tool are available within `the grm user manual
<https://aedev.readthedocs.io/en/latest/man/git_repo_manager.html>`__.


using `git` and `Gitlab`
^^^^^^^^^^^^^^^^^^^^^^^^

alternatively to the ``grm`` tool you could directly use the `git command suite <https://git-scm.com/docs>`__ and the
`Gitlab website <https://gitlab.com>`__ to achieve the same (with a lot more of typing and fiddling ;-):

1. fork the `upstream repository <https://gitlab.com/ae-group/ae_oaio_client>`__ into your user account.

2. clone your forked repo as ``origin`` remote to your computer, and add an ``upstream`` remote for the destination
   repo by running the following commands in the console of your local machine::

      git clone https://gitlab.com/<YourGitLabUserName>/ae_oaio_client.git
      git remote add upstream https://gitlab.com/ae-group/ae_oaio_client.git

3. checkout out a new local feature branch and update it to the latest version of the ``develop`` branch::

      git checkout -b <new_feature_or_fix_branch_name> develop
      git pull --rebase upstream develop

   please keep your code clean by staying current with the ``develop`` branch, where code will be merged. if you
   find another bug, please fix it in a separated branch instead.

4. push the branch to your fork. treat it as a backup::

      git push origin <new_feature_or_fix_branch_name>

5. code

   implement the new feature or the bug fix; include tests, and ensure they pass.

6. check

   run the basic code style and typing checks locally (pylint, mypy and flake8) before you commit.

7. commit

   for every commit please write a short summary in the first line followed with a blank line and then more detailed
   descriptions of the change. for bug fixes please include any issue number (in the format #nnn) in your summary::

      git commit -m "issue #123: put change summary here (can be a issue title)"

   .. note::
      **never leave the commit message blank!** provide a detailed, clear, and complete description of your changes!

8. publish your changes (prepare a Merge Request)

   before submitting a `merge request <https://docs.gitlab.com/ce/workflow/forking_workflow.html#merging-upstream>`__,
   update your branch to the latest code::

      git pull --rebase upstream develop

   if you have made many commits, we ask you to squash them into atomic units of work. most issues should have one
   commit only, especially bug fixes, which makes them easier to back port::

      git checkout develop
      git pull --rebase upstream develop
      git checkout <new_feature_or_fix_branch_name>
      git rebase -i develop

   push changes to your fork::

      git push -f

9. issue/make a GitLab Merge Request:

   * navigate to your fork where you just pushed to
   * click `Merge Request`
   * in the branch field write your feature branch name (this is filled with your default branch name)
   * click `Update Commit Range`
   * ensure the changes you implemented are included in the `Commits` tab
   * ensure that the `Files Changed` tab incorporate all of your changes
   * fill in some details about your potential patch including a meaningful title
   * click `New merge request`.


release to PyPI
---------------

the release of a new/changed project will automatically be initiated by the GitLab CI, using the two
protected vars ``PYPI_USERNAME`` and ``PYPI_PASSWORD`` (marked as masked) from the users group of this namespace, in
order to provide the user name and password of the maintainers PyPI account (on Gitlab.com at Settings/CI_CD/Variables).


useful links and resources
--------------------------

- `General GitLab documentation <https://docs.gitlab.com/ce/>`__
- `GitLab workflow documentation <https://docs.gitlab.com/ee/user/project/repository/forking_workflow.html>`__
- grm (git repository manager) module
  :mod:`project repository <aedev.git_repo_manager>`  and
  `user manual <https://aedev.readthedocs.io/en/latest/man/git_repo_manager.html>`__
