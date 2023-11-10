#!/usr/bin/python
import time

DOCUMENTATION = '''
---
module: server

short_description: Manage server in GleSYS Cloud (https://cloud.glesys.com)

version_added: "2.4"

description:
    - "Integration with GleSYS Cloud to create, update and remove servers."

options:
    id:
        description:
            - identifier for the server in GleSYS cloud
        required: false
    hostname:
        description:
            - hostname used to identify the server
        required: false
    cpus:
        description:
            - number of cpu cores
        required: false
        default: 1
    memory:
        description:
            - amount of memory in Mb
        required: false
        default: 2048
    disk:
        description:
            - disk size in Gb
        required: false
        default: 20



author:
    - Magnus Johansson <magnus@glesys.se>
    - Lars Dunemark <lars.dunemark@glesys.se>
    - Andreas Nilsson <andreas.nilsson@glesys.se>
'''

EXAMPLES = '''
- name: test my new module
  connection: local
  hosts: localhost

  vars:
    glesys_project: clxxxxxx
    glesys_key: zzzzzzzzzzzz

  tasks:
  - name: create new server at glesys
    glesys.cloud.server:
      hostname: host01.example.com
      state: present
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"
      cpus: 1
      memory: 2048
      disk: 20
      password: 'superSecureRootPassword'
      ssh_pub_key: ''
      datacenter: 'Falkenberg'
      template: 'Ubuntu 18.04 LTS 64-bit'
      platform: 'VMware'
      wait: true
      wait_timeout: 600
    register: server

  - debug:
      msg: "ID is {{ server.server.serverid }}, current state is {{ server.server.state }}"

  - debug:
      msg: "IP is {{ item.ipaddress }}"
    with_items: "{{ server.server.iplist }}"

  - name: stopp server
    glesys.cloud.server:
      hostname: host01.example.com
      state: stopped
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"

  - name: reboot server
    glesys.cloud.server:
      hostname: host01.example.com
      state: rebooted
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"

  - name: poweron server
    glesys.cloud.server:
      hostname: host01.example.com
      state: running
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"

  - name: update disk
    glesys.cloud.server:
      serverid: wpsXXXXXXX
      disk: 40
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"

  - name: Change hostname
    glesys.cloud.server:
      serverid: wpsxxxxx
      hostname: bengt.se
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"

  - name: Remove server
    glesys.cloud.server:
      id: server.id  # Or hostname
      state: absent
      project: "{{glesys_project}}"
      apikey: "{{glesys_api_key}}"
'''

RETURN = '''
server:
    id: The id of the server in GleSYS cloud
    ipv4: array of ipv4 address to the server
    ipv6: array of ipv6 address to the server
'''
import sys

sys.path.append('lib')

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible.module_utils.urls import fetch_url
from ansible.module_utils.urls import basic_auth_header
from ansible.module_utils._text import to_text


class AnsibleGlesysServer:

    def to_json(self):
        return self.properties

    def __init__(self, json, api):
        self.api = api
        self.properties = {}
        self.properties.update(json)

    def serverid(self):
        return self.properties["serverid"]

    def hostname(self):
        return self.properties["hostname"]

    def state(self):
        return self.properties["state"]

    def update(self):
        server_details = self.api.get_server_details(self.serverid())
        self.properties.update(server_details["response"]["server"])

    def update_state(self):
        state = self.api.get_server_status(self.serverid())
        self.properties["state"] = state


class GlesysApi:
    GLESYS_API_ENDPOINT = "https://api.glesys.com/"

    def __init__(self, module, project, apikey):
        self.module = module
        self.project = project
        self.apikey = apikey

    def list_server(self):
        data = self.query("server", "list")

        servers = []
        for serverData in data["response"]["servers"]:
            servers.append(AnsibleGlesysServer(serverData, api=self))
        return servers

    def find(self, serverid=None, hostname=None):
        if not serverid and not hostname:
            return None

        servers = self.list_server()

        for server in servers:
            if server.serverid() == serverid:
                return server

        for server in servers:
            if server.hostname() == hostname:
                return server

        return None

    def get_server(self, serverid=None, hostname=None):
        s = self.find(serverid, hostname)

        if s is not None:
            s.update()

        return s

    def get_server_status(self, serverid=None):
        data = self.query("server", "status", {"serverid": serverid})

        return data["response"]["server"]["state"]

    def get_server_details(self, serverid):
        return self.query("server", "details", {"serverid": serverid, "includestate": "true"})

    def stop_server(self, serverid):
        return self.post("server", "stop", {"serverid": serverid})

    def start_server(self, serverid):
        return self.post("server", "start", {"serverid": serverid})

    def reboot_server(self, serverid):
        return self.post("server", "reboot", {"serverid": serverid})

    def create_server(self, hostname, datacenter, platform, template, cpus=2,
                      memory=4096, disk=20, password=None, bandwidth=100, description=None, users=None, ssh_pub_key=None):
        if len(password) < 1:
            password =generate_temp_password(64)


        params = {
            "hostname": hostname,
            "platform": platform,
            "datacenter": datacenter,
            "templatename": template,
            "disksize": disk,
            "memorysize": memory,
            "cpucores": cpus,
            "bandwidth": bandwidth,
            "rootpassword" :  password,
            "description": description,
            "users": users,
            "ssh_pub_key": ssh_pub_key
        }

        serverjson = self.post("server", "create", params)
        return serverjson["response"]["server"]

    def remove_server(self, serverid):
        params = {
            "serverid": serverid,
            "keepip": "false"
        }

        serverjson = self.post("server", "destroy", params)
        return serverjson

    def nop(self, serverid):
        pass

    def set_power_state(self, serverid, current_state, target_state):
        transition = {
            "present": self.nop,
            "running": self.start_server,
            "stopped": self.stop_server,
            "rebooted": self.reboot_server
        }

        if current_state == target_state:
            return False

        transition[target_state](serverid)

        return True

    def update_server(self, server, params):
        params = {k: v for k, v in params.items() if v}
        params = {k: v for k, v in params.items() if v != server.to_json()[k]} # We don't need to document this

        if len(params) == 0:
            return False, None

        params["serverid"] = server.serverid()
        serverjson = self.post("server", "edit", params)

        return True, serverjson

    def parse_response(self, info, response):
        status_code = info["status"]
        if status_code >= 400:
            error = self.module.from_json(info['body'])

            self.module.fail_json(msg=error["response"]["status"]["text"])
        
        res = response.read()
        if not res:
            return {}

        return self.module.from_json(to_text(res))

    def query(self, module, func, data=None):
        url = self.GLESYS_API_ENDPOINT + module + "/" + func
        if data:
            for k, v in data.items():
                if v is not None:
                    url += "/" + k + "/" + v
        response, info = fetch_url(
            module=self.module,
            url=url,
            method="GET",
            timeout=20,
            headers={
                "Accept": "application/json",
                "Authorization": basic_auth_header(self.project, self.apikey)
            },
        )

        return self.parse_response(info, response)

    def post(self, module, func, data=None):
        url = self.GLESYS_API_ENDPOINT + module + "/" + func
        params = None

        if data:
            params = self.module.jsonify(data)

        response, info = fetch_url(
            module=self.module,
            url=url,
            method="POST",
            timeout=20,
            headers={
                "Accept": "application/json",
                "Content-type": "application/json",
                "Authorization": basic_auth_header(self.project, self.apikey)
            },
            data=params
        )
        return self.parse_response(info, response)


class GlesysRunner(object):

    def __init__(self, module):
        self.module = module
        self.api = GlesysApi(self.module, self.module.params["project"], self.module.params["apikey"])

    def create_server(self):
        if self.module.check_mode:
            self.module.exit_json(changed=True, server=None)

        #    module.fail_json(msg="server not found and serverid specified,"
        #                             " use hostname to create new servers")

        server_json = self.api.create_server(hostname=self.module.params.get("hostname"),
                                        datacenter=self.module.params.get("datacenter"),
                                        platform=self.module.params.get("platform"),
                                        template=self.module.params.get("template"),
                                        cpus=self.module.params.get("cpus"),
                                        memory=self.module.params.get("memory"),
                                        disk=self.module.params.get("disk"),
                                        password=self.module.params.get("password"),
                                        ssh_pub_key=self.module.params.get("ssh_pub_key"),
                                        bandwidth=self.module.params.get("bandwidth"),
                                        description=self.module.params.get("description"),
                                        users=self.module.params.get("users"))

        # TODO: wait
        return AnsibleGlesysServer(server_json, self.api)

    def wait_for_server_state(self, serverid, target_state):
        while True:
            active_state = self.api.get_server_status(serverid)
            print("state: " + active_state)

            if target_state == "present":
                break

            if target_state == active_state:
                break

            time.sleep(1)

    def wait_for_server_lock(self, serverid):
        active_state = self.api.get_server_status(serverid)
        while active_state == "locked":
            time.sleep(1)
            active_state = self.api.get_server_status(serverid)

    def run(self):
        server = self.api.get_server(self.module.params["serverid"], self.module.params["hostname"])

        state = self.module.params['state']

        if state == "absent":
            if server is None:
                # Server not found OK.
                self.module.exit_json(changed=False, msg="Server already absent")
            else:
                self.wait_for_server_lock(server.serverid())
                self.api.remove_server(server.serverid())
                self.module.exit_json(changed=True, msg="Server " + server.serverid() + " deleted")

        # Server should be created or updated.

        if state == "present":
            changed = False
            if server is None:
                # Server not found, go ahead and create the server.
                server = self.create_server()
                self.wait_for_server_state(server.serverid(), "running")
                time.sleep(1)
                changed = True
            else:
                # Server found , do necessary changes
                changed, server = self.update_server(server, changed)

            self.wait_for_server_lock(server.serverid())

            # server.update_state()
            # if self.api.set_power_state(server.serverid(), server.state(), self.module.params["state"]):
            #     changed = True

            server.properties["ipaddress"] = ""
            for i in server.properties["iplist"]:
                if i["version"] == 4:
                    server.properties["ipaddress"] = i["ipaddress"]
                    break
                if i["version"] == 6:
                    server.properties["ipaddress"] = i["ipaddress"]

        # wait for server
        if self.module.params['wait']:
            target_state = self.module.params['state'];
            if target_state == "rebooted":
                target_state = "running"
            self.wait_for_server_state(server.serverid(), target_state)

        server.update()

        self.module.exit_json(changed=changed, server=server.to_json())

    def update_server(self, server, changed):

        serverdetails = self.api.get_server_details(server.serverid())["response"]["server"]
        if (serverdetails['cpucores']   != self.module.params['cpus']   or
            serverdetails['disksize']   != self.module.params['disk']   or
            serverdetails['memorysize'] != self.module.params['memory'] or
            serverdetails['hostname']   != self.module.params['hostname']
            or (
                serverdetails['supportedfeatures']['editbandwidth'] == "yes" and
                serverdetails['bandwidth']   != self.module.params['bandwidth']
            )
            ):

            changed, serverjson = self.api.update_server(server, {
                "cpucores": self.module.params['cpus'],
                "disksize": self.module.params['disk'],
                "memorysize": self.module.params['memory'],
                "bandwidth": self.module.params['bandwidth'],
                "hostname": self.module.params['hostname']
            })
            if serverjson is not None:
                server = AnsibleGlesysServer(serverjson["response"]["server"], self.api)
            server.update()
            # wait for server
            if self.module.params['wait']:
                self.wait_for_server_lock(server.serverid())
            changed = True
        return changed, server

def generate_temp_password(length):
    if not isinstance(length, int) or length < 8:
        raise ValueError("temp password must have positive length")

    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    from os import urandom
    return "".join(chars[c % len(chars)] for c in urandom(length))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            project=dict(
                aliases=['PROJECT'],
                fallback=(env_fallback, ['GLESYS_PROJECT'])
            ),
            apikey=dict(
                aliases=['APIKEY'],
                no_log=True,
                fallback=(env_fallback, ['GLESYS_API_KEY'])
            ),
            serverid=dict(type='str', required=False, default=None),
            hostname=dict(type='str', required=False, default=None),
            cpus=dict(type='int', required=False, default=None),
            memory=dict(type='int', required=False, default=None),
            disk=dict(type='int', required=False, default=None),
            bandwidth=dict(type='int', required=False, default="100"),
            password=dict(type='str', required=False, default="", no_log=True),
            ssh_pub_key=dict(type='str', required=False, default=None),
            datacenter=dict(type='str', required=False, default="Falkenberg"),
            template=dict(type='str', required=False, default="Debian 9 64-bit"),
            platform=dict(type='str', required=False, default="VMware"),
            state=dict(type='str', required=False, default="present"),
            users=dict(type='raw', required=False, default=None),
            description=dict(type='str', required=False, default=None),
            wait=dict(type='bool', required=False, default=True),
            wait_timeout=dict(type='int', required=False, default="600")
        ),
        supports_check_mode=True,
        required_one_of=(
            ['serverid', 'hostname'],
        )
    )

    runner = GlesysRunner(module)

    runner.run()


if __name__ == '__main__':
    main()
