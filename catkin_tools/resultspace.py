# Copyright 2015 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

try:
    from md5 import md5
except ImportError:
    from hashlib import md5
import os
import re

try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote

from osrf_pycommon.process_utils import execute_process

from .common import parse_env_str
from .common import string_type
from .utils import which

CATKIN_EXEC = which('catkin')
DEFAULT_SHELL = '/bin/bash'

# Cache for result-space environments
_resultspace_env_cache = {}
_resultspace_env_hooks_cache = {}


def get_resultspace_environment(result_space_path, base_env={}, quiet=False, cached=True, strict=True):
    """Get the environemt variables which result from sourcing another catkin
    workspace's setup files as the string output of `cmake -E environment`.
    This cmake command is used to be as portable as possible.

    :param result_space_path: path to a Catkin result-space whose environment should be loaded, ``str``
    :type result_space_path: str
    :param quiet: don't throw exceptions, ``bool``
    :type quiet: bool
    :param cached: use the cached environment
    :type cached: bool
    :param strict: require the ``.catkin`` file exists in the resultspace
    :type strict: bool

    :returns: a dictionary of environment variables and their values
    """

    # Get the MD5 checksums for the current env hooks
    # TODO: the env hooks path should be defined somewhere
    env_hooks_path = os.path.join(result_space_path, 'etc', 'catkin', 'profile.d')
    if os.path.exists(env_hooks_path):
        env_hooks = [
            md5(open(os.path.join(env_hooks_path, path)).read().encode('utf-8')).hexdigest()
            for path in os.listdir(env_hooks_path)]
    else:
        env_hooks = []

    # Check the cache first, if desired
    if cached:
        cached_env_hooks = _resultspace_env_hooks_cache.get(result_space_path, [])
        if result_space_path in _resultspace_env_cache and env_hooks == cached_env_hooks:
            return dict(_resultspace_env_cache[result_space_path])

    # Check to make sure result_space_path is a valid directory
    if not os.path.isdir(result_space_path):
        if quiet:
            return dict()
        raise IOError(
            "Cannot load environment from resultspace \"%s\" because it does not "
            "exist." % result_space_path
        )

    # Check to make sure result_space_path contains a `.catkin` file
    # TODO: `.catkin` should be defined somewhere as an atom in catkin_pkg
    if strict and not os.path.exists(os.path.join(result_space_path, '.catkin')):
        if quiet:
            return dict()
        raise IOError(
            "Cannot load environment from resultspace \"%s\" because it does not "
            "appear to be a catkin-generated resultspace (missing .catkin marker "
            "file)." % result_space_path
        )

    # Determine the shell to use to source the setup file
    shell_path = os.environ.get('SHELL', None)
    if shell_path is None:
        shell_path = DEFAULT_SHELL
        if not os.path.isfile(shell_path):
            raise RuntimeError(
                "Cannot determine shell executable. "
                "The 'SHELL' environment variable is not set and "
                "the default '{0}' does not exist.".format(shell_path)
            )
    (_, shell_name) = os.path.split(shell_path)

    # Use fallback shell if using a non-standard shell
    if shell_name not in ['bash', 'zsh']:
        shell_name = 'bash'

    # Check to make sure result_space_path contains the appropriate setup file
    setup_file_path = os.path.join(result_space_path, 'env.sh')
    if not os.path.exists(setup_file_path):
        if quiet:
            return dict()
        raise IOError(
            "Cannot load environment from resultspace \"%s\" because the "
            "required setup file \"%s\" does not exist." % (result_space_path, setup_file_path)
        )

    # Make sure we've found CMAKE and SORT executables
    if CATKIN_EXEC is None:
        print("WARNING: Failed to find 'catkin' executable. How are you running this?")
        return {}

    # Construct a command list which sources the setup file and prints the env to stdout
    norc_flags = {'bash': '--norc', 'zsh': '-f'}
    subcommand = '{} {} env -q'.format(
        cmd_quote(setup_file_path),
        CATKIN_EXEC)

    command = [
        shell_path,
        norc_flags[shell_name],
        '-c', subcommand]

    # Define some "blacklisted" environment variables which shouldn't be copied
    blacklisted_keys = ('_', 'PWD')
    env_dict = {}

    try:
        # Run the command synchronously to get the resultspace environmnet
        lines = ''
        for ret in execute_process(command, cwd=os.getcwd(), env=base_env, emulate_tty=True):
            if type(ret) is bytes:
                ret = ret.decode()
            if isinstance(ret, string_type):
                lines += ret

        # Extract the environment variables
        env_dict = {
            k: v
            for k, v in parse_env_str(lines).items()
            if k not in blacklisted_keys
        }

        # Check to make sure we got some kind of environment
        if len(env_dict) > 0:
            # Cache the result
            _resultspace_env_cache[result_space_path] = env_dict
            _resultspace_env_hooks_cache[result_space_path] = env_hooks
        else:
            print("WARNING: Sourced environment from `{}` has no environment variables. Something is wrong.".format(
                setup_file_path))

    except IOError as err:
        print("WARNING: Failed to extract environment from resultspace: {}: {}".format(
            result_space_path, str(err)),
            file=sys.stderr)

    return dict(env_dict)


def load_resultspace_environment(result_space_path, cached=True):
    """Load the environemt variables which result from sourcing another
    workspace path into this process's environment.

    :param result_space_path: path to a Catkin result-space whose environment should be loaded, ``str``
    :type result_space_path: str
    :param cached: use the cached environment
    :type cached: bool
    """
    env_dict = get_resultspace_environment(result_space_path, cached=cached)
    os.environ.update(env_dict)
