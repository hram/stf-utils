import six
from common.stfapi import SmartphoneTestingFarmAPI
from common import adb
import threading
import json
import os
import time


class SmartphoneTestingFarmClient(SmartphoneTestingFarmAPI):
    def __init__(self, host, common_api_path, oauth_token, device_spec, shutdown_emulator_on_disconnect, devices_file_path):
        super(SmartphoneTestingFarmClient, self).__init__(host, common_api_path, oauth_token)
        self.device_groups = []
        self.device_spec = device_spec
        self.devices_file_path = devices_file_path
        self.shutdown_emulator_on_disconnect = shutdown_emulator_on_disconnect
        for wanted_device_group in self.device_spec:
            self.device_groups.append(
                {
                    "group_name": wanted_device_group.get("group_name"),
                    "wanted_amount": wanted_device_group.get("amount"),
                    "specs": wanted_device_group.get("specs"),
                    "added_devices": [],
                    "connected_devices": []
                }
            )
        self.all_devices_are_connected = False

    def connect_devices(self):
        available_devices = self._get_available_devices()
        self.all_devices_are_connected = True
        for device_group in self.device_groups:
            wanted_amount = int(device_group.get("wanted_amount"))
            actual_amount = len(device_group.get("connected_devices"))
            if actual_amount < wanted_amount:
                self.all_devices_are_connected = False
                appropriate_devices = self._filter_devices(available_devices, device_group.get("specs"))
                devices_to_connect = appropriate_devices[:wanted_amount - actual_amount]
                self._add_devices_to_group(devices_to_connect, device_group)
                self._connect_devices_to_group(devices_to_connect, device_group)

    def _add_devices_to_group(self, devices_to_add, device_group):
        for device in devices_to_add:
            self.add_device(serial=device.get("serial"))
            device_group.get("added_devices").append(device)

    def _connect_devices_to_group(self, devices_to_connect, device_group):
        for device in devices_to_connect:
            resp = self.remote_connect(serial=device.get("serial"))
            content = resp.json()
            remote_connect_url = content.get("remoteConnectUrl")
            try:
                adb.connect(remote_connect_url)
                device["remoteConnectUrl"] = remote_connect_url
                device_group.get("connected_devices").append(device)
                self._add_device_to_file(device)
            except TypeError:
                print("Error during connecting device by adb connect")
                continue

    def close_all(self):
        self._disconnect_all()
        self._delete_all()

    def _add_device_to_file(self, device):
        try:
            with open(self.devices_file_path, 'a+') as mapping_file:
                json_mapping = json.dumps({
                    "adb_url": device.get("remoteConnectUrl"),
                    "serial": device.get("serial")
                })
                mapping_file.write("{0}\n".format(json_mapping))
        except PermissionError:
            print("PermissionError: Can't open file {0}".format(self.devices_file_path))

    def _delete_all(self):
        if os.path.exists(self.devices_file_path):
            try:
                os.remove(self.devices_file_path)
            except PermissionError:
                print("PermissionError: Can't remove file {0}".format(self.devices_file_path))

        for device_group in self.device_groups:
            while device_group.get("added_devices"):
                device = device_group.get("added_devices").pop()
                self.delete_device(serial=device.get("serial"))

    def _disconnect_all(self):
        for device_group in self.device_groups:
            while device_group.get("connected_devices"):
                device = device_group.get("connected_devices").pop()
                self._disconnect_device(device)

    def _disconnect_device(self, device):
        serial = device.get("serial")
        if self.shutdown_emulator_on_disconnect and serial.startswith('emulator'):
            remote_connect_url = device.get("remoteConnectUrl")
            adb.shutdown_emulator(remote_connect_url)
            return
        self.remote_disconnect(serial)

    def _get_all_devices(self):
        resp = self.get_all_devices()
        content = resp.json()
        return content.get("devices")

    def _get_available_devices(self):
        available_devices = []
        for device in self._get_all_devices():
            if device.get("present") and not device.get("owner"):
                available_devices.append(device)
        return available_devices

    @staticmethod
    def _filter_devices(devices, specification):
        filtered_devices = []
        for device in devices:
            device_is_appropriate = True
            for key, value in six.iteritems(specification):
                        if value not in {device.get(key), "ANY"}:
                            device_is_appropriate = False
                            break
            if device_is_appropriate:
                filtered_devices.append(device)
        return filtered_devices


class SmartphoneTestingFarmPoll(threading.Thread):
    def __init__(self, stf_client, poll_period=3):
        super(SmartphoneTestingFarmPoll, self).__init__()
        self._stopper = threading.Event()
        self.stf_client = stf_client
        self.poll_period = poll_period

    def run(self):
        last_run_time = 0
        while True:
            if self.stopped():
                break
            if self.stf_client.all_devices_are_connected:
                break
            if time.time() - last_run_time >= self.poll_period:
                self.stf_client.connect_devices()
                last_run_time = time.time()
            time.sleep(0.1)

    def stop(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.isSet()