# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import base64
import copy
import json
import urllib
import urlparse
import uuid

from keystone import config
from keystone.common import dependency
from keystone.contrib.user_registration import core
from keystone.tests import test_v3

CONF = config.CONF

BASE_URL = '/OS-REGISTRATION'
REGISTER_URL = BASE_URL + '/users'
REQUEST_NEW_ACTIVATION_KEY_URL = BASE_URL + '/users/{user_id}/activate'
PERFORM_ACTIVATION_URL = BASE_URL + '/activate/{activation_key}/users/{user_id}'
REQUEST_RESET_URL = BASE_URL + '/users/{user_id}/reset_password'
PERFORM_RESET_URL = BASE_URL + '/reset_password/{token_id}/users/{user_id}'

PROJECTS_URL = '/projects/{project_id}'
ROLES_URL = '/projects/{project_id}/users/{user_id}/roles'

class RegistrationBaseTests(test_v3.RestfulTestCase):

    EXTENSION_NAME = 'user_registration'
    EXTENSION_TO_ADD = 'user_registration_extension'

    def setUp(self):
        super(RegistrationBaseTests, self).setUp()

        # Now that the app has been served, we can query CONF values
        self.base_url = 'http://localhost/v3'
        # TODO(garcianavalon) I've put this line for dependency injection to work, 
        # but I don't know if its the right way to do it...
        self.manager = core.Manager()

        # create the default role
        keystone_role_ref = self.new_role_ref()
        keystone_role_ref['name'] = core.DEFAULT_ROLE_NAME
        keystone_role = self.assignment_api.create_role(keystone_role_ref['id'], 
                                                        keystone_role_ref)

    def new_user_ref(self, *args, **kwargs):
        user_ref = super(RegistrationBaseTests, self).new_user_ref(*args, **kwargs)
        user_ref['username'] = user_ref['name']
        return user_ref

    def _register_new_user(self, user_ref=None):
        user_ref = user_ref if user_ref else self.new_user_ref(
                                                    domain_id=self.domain_id)

        response = self.post(REGISTER_URL, body={'user': user_ref})
        return response.result['user']
        
    def _activate_user(self, user_id, activation_key, expected_status=200):
        response = self.patch(
            PERFORM_ACTIVATION_URL.format(user_id=user_id,
                                          activation_key=activation_key),
            expected_status=expected_status)

        if expected_status != 200:
            return response.result
        return response.result['user']

    def _get_default_project(self, new_user):
        response = self.get(
            PROJECTS_URL.format(project_id=new_user['default_project_id']))
        return response.result['project']

    def _get_project_user_roles(self, user_id, project_id):
        response = self.get(ROLES_URL.format(user_id=user_id,
                                             project_id=project_id))
        return response.result['roles']

    def _request_password_reset(self, user, expected_status=200):
        response = self.get(
            REQUEST_RESET_URL.format(user_id=user['id']),
            expected_status=expected_status)
        if expected_status != 200:
            return response.result
        return response.result['reset_token']

    def _reset_password(self, user, token, new_password, expected_status=200):
        response = self.patch(PERFORM_RESET_URL.format(
            user_id=user['id'],
            token_id=token['id']),
            body={'user': {'password':new_password}},
            expected_status=expected_status)

        if expected_status != 200:
            return response.result
        return response.result['user']

    def _request_new_activation_key(self, user, expected_status=200):
        response = self.get(
            REQUEST_NEW_ACTIVATION_KEY_URL.format(user_id=user['id']),
            expected_status=expected_status)

        if expected_status != 200:
            return response.result
        return response.result['activation_key']

class UserDeletedTests(RegistrationBaseTests):
    """Test all resources created for a user by this extension are
    correctly removed.
    """
    def _delete_user(self, user_id):
        return self.delete('/users/{0}'.format(user_id))

    def test_delete_before_activation(self):
        new_user_ref = self.new_user_ref(domain_id=self.domain_id)
        new_user = self._register_new_user(new_user_ref)
        response = self._delete_user(new_user['id'])

        # custom_organizations

        # check we can't activate the user anymore
        active_user = self._activate_user(
            user_id=new_user['id'],
            activation_key=new_user['activation_key'],
            expected_status=404)

        # check we can't request a new activation key
        new_activation_key = self._request_new_activation_key(
            new_user,
            expected_status=404)


    def test_delete_after_activation(self):
        new_user_ref = self.new_user_ref(domain_id=self.domain_id)
        new_user = self._register_new_user(new_user_ref)
        active_user = self._activate_user(
            user_id=new_user['id'],
            activation_key=new_user['activation_key'])
        response = self._delete_user(new_user['id'])

        # custom_organizations

        # check we can't request a password reset
        token = self._request_password_reset(
            active_user,
            expected_status=404)


class RegistrationUseCaseTests(RegistrationBaseTests):


    def test_registered_user(self):
        new_user_ref = self.new_user_ref(domain_id=self.domain_id)
        new_user = self._register_new_user(new_user_ref)

        # Check the user is not enabled
        self.assertEqual(False, new_user['enabled'])

        # Check the user comes with activation_key
        self.assertIsNotNone(new_user['activation_key'])

        # and that it has a project
        self.assertIsNotNone(new_user['default_project_id'])

    def test_default_project(self):
        new_user_ref = self.new_user_ref(domain_id=self.domain_id)
        new_user = self._register_new_user(new_user_ref)

        # Check a project with same name as user exists
        new_project = self._get_default_project(new_user)
        self.assertIsNotNone(new_project)
        self.assertEqual(new_user['name'], new_project['name'])
        # and is not enabled
        self.assertEqual(False, new_project['enabled'])

    def test_user_belongs_to_project(self):
        new_user_ref = self.new_user_ref(domain_id=self.domain_id)
        new_user = self._register_new_user(new_user_ref)

        # Check the user belongs and has a role in his default project
        new_project = self._get_default_project(new_user)
        roles = self._get_project_user_roles(new_user['id'], 
                                            new_project['id'])
        self.assertIsNotNone(roles)
        self.assertEqual(1, len(roles))

        # check that it actually is the default role
        role = roles[0]
        if core.DEFAULT_ROLE_ID:
            self.assertEqual(core.DEFAULT_ROLE_ID, role['id'])
        self.assertEqual(core.DEFAULT_ROLE_NAME, role['name'])


class ActivationUseCaseTest(RegistrationBaseTests):


    def test_activate_user(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])

        # Check the user is active
        self.assertEqual(True, active_user['enabled'])

        # Check id to be sure
        self.assertEqual(new_user['id'], active_user['id'])

    def test_default_project_active(self):
        new_user = self._register_new_user()
        new_project = self._get_default_project(new_user)
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        active_project = self._get_default_project(new_user)

        # Check the project is active
        self.assertEqual(True, active_project['enabled'])

        # Check id to be sure
        self.assertEqual(new_project['id'], active_project['id'])


class ResetPasswordUseCaseTest(RegistrationBaseTests):

    def test_get_reset_token(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        token = self._request_password_reset(active_user)

        # check we have the token
        self.assertIsNotNone(token['id'])

    def test_reset_password(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        token = self._request_password_reset(active_user)

        new_password = 'new_password'
        reset_user = self._reset_password(active_user, token, new_password)

        # check the new password is correct
        auth_data = self.build_authentication_request(username=reset_user['name'],
                                            user_domain_id=reset_user['domain_id'],
                                            password=new_password)
        self.post('/auth/tokens', body=auth_data)

        # check user id, to be sure
        self.assertEqual(active_user['id'], reset_user['id'])

    def test_reset_twice_reset_token(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        old_token = self._request_password_reset(active_user)
        # request again
        new_token = self._request_password_reset(active_user)

        # check we have the token
        self.assertIsNotNone(new_token['id'])

    def test_reset_twice_reset_password(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        old_token = self._request_password_reset(active_user)
        # request again
        new_token = self._request_password_reset(active_user)

        new_password = 'new_password'
        reset_user = self._reset_password(active_user, new_token, new_password)

        # check the new password is correct
        auth_data = self.build_authentication_request(username=reset_user['name'],
                                            user_domain_id=reset_user['domain_id'],
                                            password=new_password)
        self.post('/auth/tokens', body=auth_data)

        # check user id, to be sure
        self.assertEqual(active_user['id'], reset_user['id'])

    def test_bad_token(self):
        new_user = self._register_new_user()
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_user['activation_key'])
        correct_token = self._request_password_reset(active_user)
        bad_token = {
            'id': uuid.uuid4().hex,
        }
        new_password = 'new_password'
        reset_user = self._reset_password(active_user, bad_token, new_password,
                                        expected_status=404)

class ResendActivationKeyUseCase(RegistrationBaseTests):

    def test_resend_key(self):
        new_user = self._register_new_user()
        old_activation_key = new_user['activation_key']
        new_activation_key = self._request_new_activation_key(new_user)

        self.assertIsNotNone(new_activation_key)
        self.assertNotEqual(old_activation_key, new_activation_key['id'])

    def test_activate_with_new_key(self):
        new_user = self._register_new_user()
        new_activation_key = self._request_new_activation_key(new_user)
        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=new_activation_key['id'])
        # Check the user is active
        self.assertEqual(True, active_user['enabled'])

        # Check id to be sure
        self.assertEqual(new_user['id'], active_user['id'])

    def test_activate_with_old_key(self):
        new_user = self._register_new_user()
        old_activation_key = new_user['activation_key']
        new_activation_key = self._request_new_activation_key(new_user)

        active_user = self._activate_user(user_id=new_user['id'],
                                activation_key=old_activation_key,
                                expected_status=404)