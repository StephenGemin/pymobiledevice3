import collections
import importlib
import logging
import sys
import time
import traceback
import types
import functools
import typing

import click
import coloredlogs

from pymobiledevice3.exceptions import AccessDeniedError, ConnectionFailedToUsbmuxdError, DeprecationError, \
    DeveloperModeError, DeveloperModeIsNotEnabledError, DeviceHasPasscodeSetError, DeviceNotFoundError, \
    FeatureNotSupportedError, InternalError, InvalidServiceError, MessageNotSupportedError, MissingValueError, \
    NoDeviceConnectedError, NoDeviceSelectedError, NotEnoughDiskSpaceError, NotPairedError, OSNotSupportedError, \
    PairingDialogResponsePendingError, PasswordRequiredError, RSDRequiredError, SetProhibitedError, \
    TunneldConnectionError, UserDeniedPairingError
from pymobiledevice3.osu.os_utils import get_os_utils

coloredlogs.install(level=logging.INFO)

logging.getLogger('quic').disabled = True
logging.getLogger('asyncio').disabled = True
logging.getLogger('zeroconf').disabled = True
logging.getLogger('parso.cache').disabled = True
logging.getLogger('parso.cache.pickle').disabled = True
logging.getLogger('parso.python.diff').disabled = True
logging.getLogger('humanfriendly.prompts').disabled = True
logging.getLogger('blib2to3.pgen2.driver').disabled = True
logging.getLogger('urllib3.connectionpool').disabled = True

logger = logging.getLogger(__name__)

INVALID_SERVICE_MESSAGE = """Failed to start service. Possible reasons are:
- If you were trying to access a developer service (developer subcommand):
    - Make sure the DeveloperDiskImage/PersonalizedImage is mounted via:
      > python3 -m pymobiledevice3 mounter auto-mount

    - If your device iOS version >= 17.0:
        - Make sure you passed the --rsd option to the subcommand
          https://github.com/doronz88/pymobiledevice3#working-with-developer-tools-ios--170

- Apple removed this service

- A bug. Please file a bug report:
  https://github.com/doronz88/pymobiledevice3/issues/new?assignees=&labels=&projects=&template=bug_report.md&title=
"""

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

# Mapping of index options to import file names
# key=module name, value=relative import to module cli group
ClickGroup = collections.namedtuple("ClickGroup", "import_group short_help")
ClickCommand = collections.namedtuple("ClickCommand", "name")
# Mapping of index options to import file names
# CLI_GROUPS = {
#     'activation': 'activation',
#     'afc': 'afc',
#     'amfi': 'amfi',
#     'apps': 'apps',
#     'backup2': 'backup',
#     'bonjour': 'bonjour',
#     'companion': 'companion_proxy',
#     'crash': 'crash',
#     'developer': 'developer',
#     'diagnostics': 'diagnostics',
#     'lockdown': 'lockdown',
#     'mounter': 'mounter',
#     'notification': 'notification',
#     'pcap': 'pcap',
#     'power-assertion': 'power_assertion',
#     'processes': 'processes',
#     'profile': 'profile',
#     'provision': 'provision',
#     'remote': 'remote',
#     'restore': 'restore',
#     'springboard': 'springboard',
#     'syslog': 'syslog',
#     'usbmux': 'usbmux',
#     'webinspector': 'webinspector',
#     'version': 'version',
# }
CLI_GROUPS = {
    'activation': ClickGroup('activation:activation', 'activation options'),
    'afc': ClickGroup('afc:afc', 'FileSystem utils'),
    'amfi': ClickGroup('amfi:amfi', 'amfi options'),
    'apps': ClickGroup('apps:apps', 'application options'),
    'backup2': ClickGroup('backup:backup2', 'backup utils'),
    'bonjour': ClickGroup('bonjour:bonjour_cli', 'bonjour options'),
    'companion': ClickGroup('companion_proxy:companion', 'companion options'),
    'crash': ClickGroup('crash:crash', 'crash report options'),
    'developer': ClickGroup('developer:developer', 'developer options'),
    'diagnostics': ClickGroup('diagnostics:diagnostics', 'diagnostic options'),
    'lockdown': ClickGroup('lockdown:lockdown_group', 'lockdown options'),
    'mounter': ClickGroup('mounter:mounter', 'mounter options'),
    'notification': ClickGroup('notification:notification', 'notification options'),
    # 'pcap': 'pcap',
    # 'power-assertion': 'power_assertion',
    'processes': ClickGroup('processes:processes', 'processes cli'),
    'profile': ClickGroup('profile:profile_group', 'foo'),
    'provision': ClickGroup('provision:provision', 'provision options'),
    'remote': ClickGroup('remote:remote_cli', 'remote options'),
    'restore': ClickGroup('restore:restore', 'restore options'),
    'springboard': ClickGroup('springboard:springboard', 'springboard options'),
    'syslog': ClickGroup('syslog:syslog', 'syslog options'),
    'usbmux': ClickGroup('usbmux:usbmux_cli', 'usbmuxd options'),
    # 'version': ClickCommand('version:version'),
    'webinspector': ClickGroup('webinspector:webinspector', 'webinspector options')
}

# def _get_module(name: str) -> types.ModuleType:
#     return importlib.import_module(f'pymobiledevice3.cli.{CLI_GROUPS[name]}')

def _get_module(name: str) -> types.ModuleType:
    return importlib.import_module(f'pymobiledevice3.cli.{CLI_GROUPS[name].import_group.split(":")[0]}')


# class Pmd3Cli(click.Group):
#     # def __init__(self, **kwargs):
#     #     kwargs.pop("import_name")
#     #     super().__init__(**kwargs)
#     def list_commands(self, ctx: click.Context):
#         return CLI_GROUPS.keys()
#
#     def get_command(self, ctx: click.Context, name: str):
#         # breakpoint()
#         # print(name)
#         if name not in CLI_GROUPS.keys():
#             ctx.fail(f'No such command {name!r}.')
#         mod = _get_module(name)
#         command = mod.cli.get_command(ctx, name)
#         # if name == "usbmux":
#         #     breakpoint()
#         # breakpoint()
#         # Some cli groups have different names than the index
#         if not command:
#             command_name = mod.cli.list_commands(ctx)[0]
#             command = mod.cli.get_command(ctx, command_name)
#         return command

class Pmd3Cli(click.Group):
    def __init__(self, import_name, **kwargs):
        self._import_name = import_name
        super().__init__(**kwargs)

    @functools.cached_property
    # @property
    def _impg(self) -> click.Group:
        module, name = self._import_name.split(":", 1)
        print(f'{module=}, {name=}')
        s = time.perf_counter()
        _attr = getattr(importlib.import_module(module), name)
        e = time.perf_counter()
        print(e - s)
        _attr = getattr(importlib.import_module(module), name)
        print(time.perf_counter() - e)

        return _attr

    def get_command(self, ctx: click.Context, cmd_name: str):
        return self._impg.get_command(ctx, cmd_name)

    def list_commands(self, ctx: click.Context):
        return self._impg.list_commands(ctx)


@click.group(cls=click.Group, context_settings=CONTEXT_SETTINGS)
def cli():
    pass

# _CLI_PATH = "pymobiledevice3.cli"
# def _create_new_group(entry_point: click.Group, module, group_func):
#     entry_point.group(name=module,cls=Pmd3Cli, import_name=f"{_CLI_PATH}.{group_func}")


# ATTEMPT 1, DO NOT USE
# for k, v in CLI_GROUPS.items():
#     _func_code = f'''
# @{cli}.group(cls=Pmd3Cli, import_name=f"{_CLI_PATH}.{v}")
# def {k}():
#     """{k} options"""
#     '''
#     namespace = {}
#     exec(_func_code, namespace)
#     func = namespace[k]
#     globals()[k] = func
#     # func=_create_new_group(cli, k, v)
#     # func.__doc__ = f"{k} options"
#     # globals()[k] = func


def _create_click_group(name, group):
    """
    Create click group dynamically

    Replaces the need to do the following for each group
    @cli.group(cls=Pmd3Cli, import_name=f"{_CLI_PATH}.{CLI_GROUPS['restore']}")
    def restore():
        '''restore options'''
    """
    @cli.group(cls=Pmd3Cli, import_name=f'pymobiledevice3.cli.{group.import_group}', name=name, short_help=group.short_help)
    def new_group():
        pass
    return new_group

# def _create_click_group(name, group):
#     """
#     Create click group dynamically
#
#     Replaces the need to do the following for each subgroup
#     @cli.group(cls=Pmd3Cli, import_name=f"{_CLI_PATH}.{CLI_GROUPS['restore']}")
#     def restore():
#         '''restore options'''
#     """
#     _CLI_PATH = "pymobiledevice3.cli"
#     @cli.group(name=name, cls=Pmd3Cli)
#     def new_group():
#         pass
#     return new_group

for _k, _v in CLI_GROUPS.items():
    # m, gfunc = _v.import_group.split(":", 1)
    # mod = importlib.import_module(f"pymobiledevice3.cli.{m}")
    # breakpoint()
    # group_func = _create_click_group(_k, _v, getattr(mod, gfunc).__doc__)
    # breakpoint()
    if isinstance(_v, ClickGroup):
        group_func = _create_click_group(_k, _v)
        globals()[_k] = group_func
    else:
        group_func = _create_click_group(_k, _v)
        globals()[_k] = group_func
    #     module, name = _v.name
    #     cli.add_command(_get_module(module), name)

# def _get_cli_modules():


# @cli.group(cls=Pmd3Cli, import_name=f"{_CLI_PATH}.{CLI_GROUPS['restore']}")
# def restore():
#     pass
# from pymobiledevice3.cli.version import version
# cli.add_command(version)
# @click.group(cls=Pmd3Cli, import_name=)
# def version()

def main() -> None:
    try:
        cli()
    except NoDeviceConnectedError:
        logger.error('Device is not connected')
    except ConnectionAbortedError:
        logger.error('Device was disconnected')
    except NotPairedError:
        logger.error('Device is not paired')
    except UserDeniedPairingError:
        logger.error('User refused to trust this computer')
    except PairingDialogResponsePendingError:
        logger.error('Waiting for user dialog approval')
    except SetProhibitedError:
        logger.error('lockdownd denied the access')
    except MissingValueError:
        logger.error('No such value')
    except DeviceHasPasscodeSetError:
        logger.error('Cannot enable developer-mode when passcode is set')
    except DeveloperModeError as e:
        logger.error(f'Failed to enable developer-mode. Error: {e}')
    except ConnectionFailedToUsbmuxdError:
        logger.error('Failed to connect to usbmuxd socket. Make sure it\'s running.')
    except MessageNotSupportedError:
        logger.error('Message not supported for this iOS version')
        traceback.print_exc()
    except InternalError:
        logger.error('Internal Error')
    except DeveloperModeIsNotEnabledError:
        logger.error('Developer Mode is disabled. You can try to enable it using: '
                     'python3 -m pymobiledevice3 amfi enable-developer-mode')
    except (InvalidServiceError, RSDRequiredError) as e:
        should_retry_over_tunneld = False
        if isinstance(e, RSDRequiredError):
            logger.warning('Trying again over tunneld since RSD is required for this command')
            should_retry_over_tunneld = True
        elif (e.identifier is not None) and ('developer' in sys.argv) and ('--tunnel' not in sys.argv):
            logger.warning('Trying again over tunneld since it is a developer command')
            should_retry_over_tunneld = True
        if should_retry_over_tunneld:
            sys.argv += ['--tunnel', e.identifier]
            return main()
        logger.error(INVALID_SERVICE_MESSAGE)
    except NoDeviceSelectedError:
        return
    except PasswordRequiredError:
        logger.error('Device is password protected. Please unlock and retry')
    except AccessDeniedError:
        logger.error(get_os_utils().access_denied_error)
    except BrokenPipeError:
        traceback.print_exc()
    except TunneldConnectionError:
        logger.error(
            'Unable to connect to Tunneld. You can start one using:\n'
            'sudo python3 -m pymobiledevice3 remote tunneld')
    except DeviceNotFoundError as e:
        logger.error(f'Device not found: {e.udid}')
    except NotEnoughDiskSpaceError:
        logger.error('Not enough disk space')
    except DeprecationError:
        logger.error('failed to query MobileGestalt, MobileGestalt deprecated (iOS >= 17.4).')
    except OSNotSupportedError as e:
        logger.error(
            f'Unsupported OS - {e.os_name}. To add support, consider contributing at '
            f'https://github.com/doronz88/pymobiledevice3.')
    except FeatureNotSupportedError as e:
        logger.error(
            f'Missing implementation of `{e.feature}` on `{e.os_name}`. To add support, consider contributing at '
            f'https://github.com/doronz88/pymobiledevice3.')


def profile_command():
    # __main__._get_module("lockdown")
    print(getattr(importlib.import_module('pymobiledevice3.cli.lockdown'), 'lockdown_group'))

if __name__ == '__main__':
    import cProfile
    import importlib
    import pstats
    import time

    # s = time.perf_counter()
    # profile_command()
    # print(time.perf_counter() - s)
    cProfile.run('profile_command()', 'profile_output')
    p = pstats.Stats('profile_output')
    p.sort_stats('cumulative').print_stats()  # Print top 10 results sorted by cumulative time
    # p.sort_stats('tottime').print_stats()
