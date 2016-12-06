############################################################################
# Copyright 2016 RIFT.io Inc                                               #
#                                                                          #
# Licensed under the Apache License, Version 2.0 (the "License");          #
# you may not use this file except in compliance with the License.         #
# You may obtain a copy of the License at                                  #
#                                                                          #
#     http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                          #
# Unless required by applicable law or agreed to in writing, software      #
# distributed under the License is distributed on an "AS IS" BASIS,        #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. #
# See the License for the specific language governing permissions and      #
# limitations under the License.                                           #
############################################################################

import argparse
import asyncio
from functools import partial
import logging
import os
import ssl
import sys
import time

try:
    from jujuclient.juju1.environment import Environment as Env1
    from jujuclient.juju2.environment import Environment as Env2
except ImportError as e:
    # Try importing older jujuclient
    from jujuclient import Environment as Env1

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    # Legacy Python doesn't verify by default (see pep-0476)
    #   https://www.python.org/dev/peps/pep-0476/
    pass


class JujuVersionError(Exception):
    pass


class JujuApiError(Exception):
    pass


class JujuEnvError(JujuApiError):
    pass


class JujuModelError(JujuApiError):
    pass


class JujuStatusError(JujuApiError):
    pass


class JujuUnitsError(JujuApiError):
    pass


class JujuWaitUnitsError(JujuApiError):
    pass


class JujuSrvNotDeployedError(JujuApiError):
    pass


class JujuAddCharmError(JujuApiError):
    pass


class JujuDeployError(JujuApiError):
    pass


class JujuDestroyError(JujuApiError):
    pass


class JujuResolveError(JujuApiError):
    pass


class JujuActionError(JujuApiError):
    pass


class JujuActionApiError(JujuActionError):
    pass


class JujuActionInfoError(JujuActionError):
    pass


class JujuActionExecError(JujuActionError):
    pass


class JujuApi(object):
    '''
    JujuApi wrapper on jujuclient library

    There should be one instance of JujuApi for each VNF manged by Juju.

    Assumption:
        Currently we use one unit per service/VNF. So once a service
        is deployed, we store the unit name and reuse it
'''
    log = None

    def __init__ (self,
                  log=None,
                  loop=None,
                  server='127.0.0.1',
                  port=17070,
                  user='admin',
                  secret=None,
                  version=None):
        '''Initialize with the Juju credentials'''
        self.server = server
        self.port = port

        self.secret = secret
        if user.startswith('user-'):
            self.user = user
        else:
            self.user = 'user-{}'.format(user)

        self.loop = loop

        if log is not None:
            self.log = log
        else:
            self.log = JujuApi._get_logger()

        if self.log is None:
            raise JujuApiError("Logger not defined")

        self.version = None
        if version:
            self.version = version
        else:
            try:
                if Env2:
                    pass
            except NameError:
                self.log.warn("Using older version of Juju client, which " \
                              "supports only Juju 1.x")
                self.version = 1

        endpoint = 'wss://%s:%d' % (server, int(port))
        self.endpoint = endpoint

        self.charm = None  # Charm used
        self.service = None  # Service deployed
        self.units = []  # Storing as list to support more units in future

        self.destroy_retries = 25 # Number retires to destroy service
        self.retry_delay = 5 # seconds

    def __str__(self):
        return ("JujuApi-{}".format(self.endpoint))

    @classmethod
    def _get_logger(cls):
        if cls.log is not None:
            return cls.log

        fmt = logging.Formatter(
            '%(asctime)-23s %(levelname)-5s  (%(name)s@%(process)d:' \
            '%(filename)s:%(lineno)d) - %(message)s')
        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setFormatter(fmt)
        logging.basicConfig(level=logging.DEBUG)
        cls.log = logging.getLogger('juju-api')
        cls.log.addHandler(stderr_handler)

        return cls.log

    @staticmethod
    def format_charm_name(name):
        '''Format the name to valid charm name

        Charm service name accepts only a to z and -.
        '''

        new_name = ''
        for c in name:
            if c.isdigit():
                c = chr(97 + int(c))
            elif not c.isalpha():
                c = "-"
            new_name += c
        return new_name.lower()

    def _get_version_tag(self, tag):
        version_tag_map = {
            'applications': {
                1: 'Services',
                2: 'applications',
            },
            'units': {
                1: 'Units',
                2: 'units',
            },
            'status': {
                1: 'Status',
                2: 'status',
            },
            'workload-status': {
                1: 'Workload',
                2: 'workload-status',
            },
            'charm-url': {
                1: 'CharmURL',
                2: 'charm-url',
            },
        }

        return version_tag_map[tag][self.version]

    def _get_env1(self):
        try:
            env = Env1(self.endpoint)
            l = env.login(self.secret, user=self.user)
            return env

        except ConnectionRefusedError as e:
            msg = "{}: Failed Juju 1.x connect: {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise e

        except Exception as e:
            msg = "{}: Failed Juju 1.x connect: {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuEnvError(msg)

    def _get_env2(self):
        try:
            env = Env2(self.endpoint)
            l = env.login(self.secret, user=self.user)
        except KeyError as e:
            msg = "{}: Failed Juju 2.x connect: {}".format(self, e)
            self.log.debug(msg)
            raise JujuVersionError(msg)

        try:
            models = env.models.list()
            for m in models['user-models']:
                if m['model']['name'] == 'default':
                    mep =  '{}/model/{}/api'.format(self.endpoint,
                                                    m['model']['uuid'])
                    model = Env2(mep, env_uuid=m['model']['uuid'])
                    l = model.login(self.secret, user=self.user)
                    break

            if model is None:
                raise

            return model

        except Exception as e:
            msg = "{}: Failed logging to model: {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            env.close()
            raise JujuModelError(msg)

    def _get_env(self):
        self.log.debug("{}: Connect to endpoint {}".
                      format(self, self.endpoint))

        if self.version is None:
            # Try version 2 first
            try:
                env = self._get_env2()
                self.version = 2

            except JujuVersionError as e:
                self.log.info("Unable to login as Juju 2.x, trying 1.x")
                env = self._get_env1()
                self.version = 1

            return env

        elif self.version == 2:
            return self._get_env2()

        elif self.version == 1:
            return self._get_env1()

        else:
            msg = "{}: Unknown version set: {}".format(self, self.version)
            self.log.error(msg)
            raise JujuVersionError(msg)

    @asyncio.coroutine
    def get_env(self):
        ''' Connect to the Juju controller'''
        env = yield from self.loop.run_in_executor(
            None,
            self._get_env,
        )
        return env

    def _get_status(self, env=None):
        if env is None:
            env = self._get_env()

        try:
            status = env.status()
            return status

        except Exception as e:
            msg = "{}: exception in getting status: {}". \
                  format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuStatusError(msg)

    @asyncio.coroutine
    def get_status(self, env=None):
        '''Get Juju controller status'''
        pf = partial(self._get_status, env=env)
        status = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return status

    def get_all_units(self, status, service=None):
        '''Parse the status and get the units'''
        results = {}
        services = status.get(self._get_version_tag('applications'), {})

        for svc_name, svc_data in services.items():
            if service and service != svc_name:
                continue
            units = svc_data[self._get_version_tag('units')] or {}

            results[svc_name] = {}
            for unit in units:
                results[svc_name][unit] = \
                        units[unit][self._get_version_tag('workload-status')] \
                        [self._get_version_tag('status')] or None
        return results


    def _get_service_units(self, service=None, status=None, env=None):
        if service is None:
            service = self.service

        # Optimizing calls to Juju, as currently we deploy only 1 unit per
        # service.
        # if self.service == service and len(self.units):
        #     return self.units

        if env is None:
            env = self._get_env()

        if status is None:
            status = self._get_status(env=env)

        try:
            resp = self.get_all_units(status, service=service)
            self.log.debug("Get all units: {}".format(resp))
            units = set(resp[service].keys())

            if self.service == service:
                self.units = units

            return units

        except Exception as e:
            msg = "{}: exception in get units {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuUnitsError(msg)

    @asyncio.coroutine
    def get_service_units(self, service=None, status=None, env=None):
        '''Get the unit names for a service'''
        pf = partial(self._get_service_units,
                     service=service,
                     status=status,
                     env=env)
        units = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return units

    def _get_service_status(self, service=None, status=None, env=None):
        if env is None:
            env = self._get_env()

        if status is None:
            status = self._get_status(env=env)

        if service is None:
            service = self.service

        try:
            srv_status = status[self._get_version_tag('applications')] \
                         [service][self._get_version_tag('status')] \
                         [self._get_version_tag('status')]
            self.log.debug("{}: Service {} status is {}".
                           format(self, service, srv_status))
            return srv_status

        except KeyError as e:
            self.log.info("self: Did not find service {}, e={}".format(self, service, e))
            return 'NA'

        except Exception as e:
            msg = "{}: exception checking service status for {}, e {}". \
                  format(self, service, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuStatusError(msg)


    @asyncio.coroutine
    def get_service_status(self, service=None, status=None, env=None):
        ''' Get service status

            maintenance : The unit is not yet providing services, but is actively doing stuff.
            unknown : Service has finished an event but the charm has not called status-set yet.
            waiting : Service is unable to progress to an active state because of dependency.
            blocked : Service needs manual intervention to get back to the Running state.
            active  : Service correctly offering all the services.
            NA      : Service is not deployed
        '''
        pf = partial(self._get_service_status,
                     service=service,
                     status=status,
                     env=env)
        srv_status = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return srv_status

    def _is_service_deployed(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp not in ['terminated', 'NA']:
            return True

        return False

    @asyncio.coroutine
    def is_service_deployed(self, service=None, status=None, env=None):
        '''Check if the service is deployed'''
        pf = partial(self._is_service_deployed,
                     service=service,
                     status=status,
                     env=env)
        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _is_service_error(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp in ['error']:
            return True

        return False

    @asyncio.coroutine
    def is_service_error(self, service=None, status=None, env=None):
        '''Check if the service is in error state'''
        pf = partial(self._is_service_error,
                     service=service,
                     status=status,
                     env=env)
        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _is_service_maint(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp in ['maintenance']:
            return True

        return False

    @asyncio.coroutine
    def is_service_maint(self, service=None, status=None, env=None):
        '''Check if the service is in error state'''
        pf = partial(self._is_service_maint,
                     service=service,
                     status=status,
                     env=env)
        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _is_service_active(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp in ['active']:
            return True

        return False

    @asyncio.coroutine
    def is_service_active(self, service=None, status=None, env=None):
        '''Check if the service is active'''
        pf = partial(self._is_service_active,
                     service=service,
                     status=status,
                     env=env)
        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _is_service_blocked(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp in ['blocked']:
            return True

        return False

    @asyncio.coroutine
    def is_service_blocked(self, service=None, status=None, env=None):
        '''Check if the service is blocked'''
        pf = partial(self._is_service_blocked,
                     service=service,
                     status=status,
                     env=env)
        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _is_service_up(self, service=None, status=None, env=None):
        resp = self._get_service_status(service=service,
                                        status=status,
                                        env=env)

        if resp in ['active', 'blocked']:
            return True

        return False

    @asyncio.coroutine
    def is_service_up(self, service=None, status=None, env=None):
        '''Check if the service is installed and up'''
        pf = partial(self._is_service_up,
                     service=service,
                     status=status,
                     env=env)

        rc = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return rc

    def _apply_config(self, config, service=None, env=None):
        if service is None:
            service = self.service

        if config is None or len(config) == 0:
            self.log.warn("{}: Empty config passed for service {}".
                          format(self, service))
            return

        if env is None:
            env = self._get_env()

        status = self._get_status(env=env)

        if not self._is_service_deployed(service=service,
                                         status=status,
                                         env=env):
            raise JujuSrvNotDeployedError("{}: service {} is not deployed".
                                          format(self, service))

        self.log.debug("{}: Config for service {} update to: {}".
                       format(self, service, config))
        try:
            # Try to fix error on service, most probably due to config issue
            if self._is_service_error(service=service, status=status, env=env):
                self._resolve_error(service=service, env=env)

            if self.version == 2:
                env.service.set(service, config)
            else:
                env.set_config(service, config)

        except Exception as e:
            self.log.error("{}: exception setting config for {} with {}, e {}".
                           format(self, service, config, e))
            self.log.exception(e)
            raise e

    @asyncio.coroutine
    def apply_config(self, config, service=None, env=None, wait=True):
        '''Apply a config on the service'''
        pf = partial(self._apply_config,
                     config,
                     service=service,
                     env=env)
        yield from self.loop.run_in_executor(
            None,
            pf,
        )

        if wait:
            # Wait till config finished applying
            self.log.debug("{}: Wait for config apply to finish".
                           format(self))
            delay = 3  # secs
            maint = True
            while maint:
                # Sleep first to give time for config_changed hook to be invoked
                yield from asyncio.sleep(delay, loop=self.loop)
                maint = yield from self.is_service_maint(service=service,
                                                         env=env)

        err = yield from self.is_service_error(service=service, env=env)
        if err:
            self.log.error("{}: Service is in error state".
                           format(self))
            return False

        self.log.debug("{}: Finished applying config".format(self))
        return True

    def _set_parameter(self, parameter, value, service=None):
        return self._apply_config({parameter : value}, service=service)

    @asyncio.coroutine
    def set_parameter(self, parameter, value, service=None):
        '''Set a config parameter for a service'''
        return self.apply_config({parameter : value}, service=service)

    def _resolve_error(self, service=None, status=None, env=None):
        if env is None:
            env = self._get_env()

        if status is None:
            status = self._get_status(env=env)

        if service is None:
            service = self.service

        if env is None:
            env = self._get_env()
        if self._is_service_deployed(service=service, status=status):
            units = self.get_all_units(status, service=service)

            for unit, ustatus in units[service].items():
                if ustatus == 'error':
                    self.log.info("{}: Found unit {} with status {}".
                                  format(self, unit, ustatus))
                    try:
                        # Takes the unit name as service_name/idx unlike action
                        env.resolved(unit)

                    except Exception as e:
                        msg = "{}: Resolve on unit {}: {}". \
                              format(self, unit, e)
                        self.log.warn(msg)

    @asyncio.coroutine
    def resolve_error(self, service=None, status=None, env=None):
        '''Resolve units in error state'''
        pf = partial(self._resolve_error,
                     service=service,
                     status=status,
                     env=env)
        yield from self.loop.run_in_executor(
            None,
            pf,
        )

    def _deploy_service(self, charm, service,
                        path=None, config=None, env=None):
        self.log.debug("{}: Deploy service for charm {}({}) with service {}".
                       format(self, charm, path, service))

        if env is None:
            env = self._get_env()

        self.service = service
        self.charm = charm

        if self._is_service_deployed(service=service, env=env):
            self.log.info("{}: Charm service {} already deployed".
                          format (self, service))
            if config:
                self._apply_config(config, service=service, env=env)
            return

        series = "trusty"

        deploy_to = None
        if self.version == 1:
            deploy_to = "lxc:0"

        if path is None:
            prefix=os.getenv('RIFT_INSTALL', '/')
            path = os.path.join(prefix, 'usr/rift/charms', series, charm)

        try:
            self.log.debug("{}: Local charm settings: dir={}, series={}".
                           format(self, path, series))
            result = env.add_local_charm_dir(path, series)
            url = result[self._get_version_tag('charm-url')]

        except Exception as e:
            msg = '{}: Error setting local charm directory {} for {}: {}'. \
                  format(self, path, service, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuAddCharmError(msg)

        try:
            self.log.debug("{}: Deploying using: service={}, url={}, to={}, config={}".
                           format(self, service, url, deploy_to, config))
            env.deploy(service, url, config=config, machine_spec=deploy_to)

        except Exception as e:
            msg = '{}: Error deploying {}: {}'.format(self, service, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuDeployError(msg)

    @asyncio.coroutine
    def deploy_service(self, charm, service,
                       wait=False, timeout=300,
                       path=None, config=None):
        '''Deploy a service using the charm name provided'''
        env = yield from self.get_env()

        pf = partial(self._deploy_service,
                     charm,
                     service,
                     path=path,
                     config=config,
                     env=env)
        yield from self.loop.run_in_executor(
            None,
            pf,
        )

        rc = True
        if wait is True:
            # Wait for the deployed units to start
            try:
                self.log.debug("{}: Waiting for service {} to come up".
                               format(self, service))
                rc = yield from self.wait_for_service(timeout=timeout, env=env)

            except Exception as e:
                msg = '{}: Error starting all units for {}: {}'. \
                      format(self, service, e)
                self.log.error(msg)
                self.log.exception(e)
                raise JujuWaitUnitsError(msg)

        return rc

    @asyncio.coroutine
    def wait_for_service(self, service=None, timeout=0, env=None):
        '''Wait for the service to come up'''
        if service is None:
            service = self.service

        if env is None:
            env = yield from self.get_env()

        status = yield from self.get_status(env=env)

        if self._is_service_up(service=service, status=status, env=env):
            self.log.debug("{}: Service {} is already up".
                               format(self, service))
            return True

        # Check if service is deployed
        if not self._is_service_deployed(service=service, status=status, env=env):
            raise JujuSrvNotDeployedError("{}: service {} is not deployed".
                                          format(self, service))

        if timeout < 0:
            timeout = 0

        count = 0
        delay = self.retry_delay # seconds
        self.log.debug("{}: In wait for service {}".format(self, service))

        start_time = time.time()
        max_time = time.time() + timeout
        while timeout != 0 and (time.time() <= max_time):
            count += 1
            rc = yield from self.is_service_up(service=service, env=env)
            if rc:
                self.log.debug("{}: Service {} is up after {} seconds".
                               format(self, service, time.time()-start_time))
                return True
            yield from asyncio.sleep(delay, loop=self.loop)
        return False

    def _destroy_service(self, service=None):
        '''Destroy a service on Juju controller'''
        self.log.debug("{}: Destroy charm service: {}".format(self,service))

        if service is None:
            service = self.service

        env = self._get_env()

        status = self._get_status(env=env)

        count = 0
        while self._is_service_deployed(service=service, status=status, env=env):
            count += 1
            self.log.debug("{}: Destroy service {}, count {}".
                           format(self, service, count))

            if count > self.destroy_retries:
                msg = "{}: Not able to destroy service {} after {} tries". \
                      format(self, service, count)
                self.log.error(msg)
                raise JujuDestroyError(msg)


            if self._is_service_error(service=service, status=status):
                self._resolve_error(service, status)

            try:
                env.destroy_service(service)

            except Exception as e:
                msg = "{}: Exception when running destroy on service {}: {}". \
                      format(self, service, e)
                self.log.error(msg)
                self.log.exception(e)
                raise JujuDestroyError(msg)

            time.sleep(self.retry_delay)
            status = self._get_status(env=env)

        self.log.debug("{}: Destroyed service {} ({})".
                       format(self, service, count))

    @asyncio.coroutine
    def destroy_service(self, service=None):
        '''Destroy a service on Juju controller'''
        pf = partial(self._destroy_service,
                     service=service)
        yield from self.loop.run_in_executor(
            None,
            pf,
        )


    def _get_action_status(self, action_tag, env=None):
        if env is None:
            env = self._get_env()

        if not action_tag.startswith('action-'):
            action_tag = 'action-{}'.format(action_tag)

        try:
            action = env.actions
        except Exception as e:
            msg = "{}: exception in Action API: {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuActionApiError(msg)

        try:
            status = action.info([{'Tag': action_tag}])

            self.log.debug("{}: Action {} status {}".
                           format(self, action_tag, status))
            return status['results'][0]

        except Exception as e:
            msg = "{}: exception in get action status {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuActionInfoError(msg)

    @asyncio.coroutine
    def get_action_status(self, action_tag, env=None):
        '''
        Get the status of an action queued on the controller

        responds with the action status, which is one of three values:

         - completed
         - pending
         - failed

         @param action_tag - the action UUID return from the enqueue method
         eg: action-3428e20d-fcd7-4911-803b-9b857a2e5ec9
        '''
        pf = partial(self._get_action_status,
                     action_tag,
                     env=env,)
        status = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return status

    def _execute_action(self, action_name, params, service=None, env=None):
        '''Execute the action on all units of a service'''
        if service is None:
            service = self.service

        if env is None:
            env = self._get_env()

        try:
            action = env.actions
        except Exception as e:
            msg = "{}: exception in Action API: {}".format(self, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuActionApiError(msg)

        units = self._get_service_units(service)
        self.log.debug("{}: Apply action {} on units {}".
                       format(self, action_name, units))

        # Rename units from <service>/<n> to unit-<service>-<n>
        unit_tags = []
        for unit in units:
            idx = int(unit[unit.index('/')+1:])
            unit_name = "unit-%s-%d" % (service, idx)
            unit_tags.append(unit_name)
        self.log.debug("{}: Unit tags for action: {}".
                       format(self, unit_tags))

        try:
            result = action.enqueue_units(unit_tags, action_name, params)
            self.log.debug("{}: Response for action: {}".
                           format(self, result))
            return result['results'][0]

        except Exception as e:
            msg = "{}: Exception enqueing action {} on units {} with " \
                  "params {}: {}".format(self, action, unit_tags, params, e)
            self.log.error(msg)
            self.log.exception(e)
            raise JujuActionExecError(msg)

    @asyncio.coroutine
    def execute_action(self, action_name, params, service=None, env=None):
        '''Execute an action for a service on the controller

        Currently, we execute the action on all units of the service
        '''
        pf = partial(self._execute_action,
                     action_name,
                     params,
                     service=service,
                     env=env)
        result = yield from self.loop.run_in_executor(
            None,
            pf,
        )
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test Juju')
    parser.add_argument("-s", "--server", default='10.0.202.49', help="Juju controller")
    parser.add_argument("-u", "--user", default='admin', help="User, default user-admin")
    parser.add_argument("-p", "--password", default='nfvjuju', help="Password for the user")
    parser.add_argument("-P", "--port", default=17070, help="Port number, default 17070")
    parser.add_argument("-d", "--directory", help="Local directory for the charm")
    parser.add_argument("--service", help="Charm service name")
    parser.add_argument("--vnf-ip", help="IP of the VNF to configure")
    args = parser.parse_args()

    api = JujuApi(server=args.server,
                  port=args.port,
                  user=args.user,
                  secret=args.password)

    env = api._get_env()
    if env is None:
        raise "Not able to login to the Juju controller"

    print("Status: {}".format(api._get_status(env=env)))

    if args.directory and args.service:
        # Deploy the charm
        charm = os.path.basename(args.directory)
        api._deploy_service(charm, args.service,
                            path=args.directory,
                            env=env)

        while not api._is_service_up():
            time.sleep(5)

        print ("Service {} is deployed with status {}".
               format(args.service, api._get_service_status()))

        if args.vnf_ip and \
           ('clearwater-aio' in args.directory):
            # Execute config on charm
            api._apply_config({'proxied_ip': args.vnf_ip})

            while not api._is_service_active():
                time.sleep(10)

            print ("Service {} is in status {}".
                   format(args.service, api._get_service_status()))

            res = api._execute_action('create-update-user', {'number': '125252352525',
                                                             'password': 'asfsaf'})

            print ("Action 'creat-update-user response: {}".format(res))

            status = res['status']
            while status not in [ 'completed', 'failed' ]:
                time.sleep(2)
                status = api._get_action_status(res['action']['tag'])['status']

                print("Action status: {}".format(status))

            # This action will fail as the number is non-numeric
            res = api._execute_action('delete-user', {'number': '125252352525asf'})

            print ("Action 'delete-user response: {}".format(res))

            status = res['status']
            while status not in [ 'completed', 'failed' ]:
                time.sleep(2)
                status = api._get_action_status(res['action']['tag'])['status']

                print("Action status: {}".format(status))
