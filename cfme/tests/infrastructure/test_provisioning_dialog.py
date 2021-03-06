# -*- coding: utf-8 -*-
"""This module tests various ways how to set up the provisioning using the provisioning dialog."""
import re
from datetime import datetime, timedelta

import fauxfactory
import pytest
from cfme import test_requirements
from cfme.common.provider import cleanup_vm
from cfme.infrastructure.virtual_machines import Vm
from cfme.infrastructure.provider import InfraProvider
from cfme.infrastructure.provider.rhevm import RHEVMProvider
from cfme.provisioning import provisioning_form
from cfme.services import requests
from cfme.web_ui import InfoBlock, fill, flash
from utils import testgen
from utils.appliance.implementations.ui import navigate_to
from utils.blockers import BZ
from utils.generators import random_vm_name
from utils.log import logger
from utils.version import current_version
from utils.wait import wait_for, TimedOutError

pytestmark = [
    pytest.mark.meta(server_roles="+automate"),
    pytest.mark.usefixtures('uses_infra_providers'),
    pytest.mark.long_running,
    test_requirements.provision,
    pytest.mark.meta(blockers=[
        BZ(
            1265466,
            unblock=lambda provider: not provider.one_of(RHEVMProvider))
    ]),
    pytest.mark.tier(3)
]


pytest_generate_tests = testgen.generate([InfraProvider], required_fields=[
    ['provisioning', 'template'],
    ['provisioning', 'host'],
    ['provisioning', 'datastore']
], scope="module")


@pytest.fixture(scope="function")
def vm_name():
    vm_name = random_vm_name('provd')
    return vm_name


@pytest.fixture(scope="function")
def prov_data(provisioning, provider):
    data = {
        "first_name": fauxfactory.gen_alphanumeric(),
        "last_name": fauxfactory.gen_alphanumeric(),
        "email": "{}@{}.test".format(
            fauxfactory.gen_alphanumeric(), fauxfactory.gen_alphanumeric()),
        "manager_name": "{} {}".format(
            fauxfactory.gen_alphanumeric(), fauxfactory.gen_alphanumeric()),
        "vlan": provisioning.get("vlan", None),
        # "datastore_create": False,
        "datastore_name": {"name": provisioning["datastore"]},
        "host_name": {"name": provisioning["host"]},
        # "catalog_name": provisioning["catalog_item_type"],
    }

    if provider.type == 'rhevm':
        data['provision_type'] = 'Native Clone'
    elif provider.type == 'virtualcenter':
        data['provision_type'] = 'VMware'
    # Otherwise just leave it alone

    return data


@pytest.fixture(scope="function")
def provisioner(request, setup_provider, provider, vm_name):

    def _provisioner(template, provisioning_data, delayed=None):
        vm = Vm(name=vm_name, provider=provider, template_name=template)
        navigate_to(vm, 'ProvisionVM')

        fill(provisioning_form, provisioning_data, action=provisioning_form.submit_button)
        flash.assert_no_errors()

        request.addfinalizer(lambda: cleanup_vm(vm_name, provider))
        if delayed is not None:
            total_seconds = (delayed - datetime.utcnow()).total_seconds()
            row_description = 'Provision from [{}] to [{}]'.format(template, vm_name)
            cells = {'Description': row_description}
            try:
                row, __ = wait_for(requests.wait_for_request, [cells],
                                   fail_func=requests.reload, num_sec=total_seconds, delay=5)
                pytest.fail("The provisioning was not postponed")
            except TimedOutError:
                pass
        logger.info('Waiting for vm %s to appear on provider %s', vm_name, provider.key)
        wait_for(provider.mgmt.does_vm_exist, [vm_name], handle_exception=True, num_sec=600)

        # nav to requests page happens on successful provision
        logger.info('Waiting for cfme provision request for vm %s', vm_name)
        row_description = 'Provision from [{}] to [{}]'.format(template, vm_name)
        cells = {'Description': row_description}
        row, __ = wait_for(requests.wait_for_request, [cells],
                           fail_func=requests.reload, num_sec=900, delay=20)
        assert 'Successfully' in row.last_message.text and row.status.text != 'Error'
        return vm

    return _provisioner


def test_change_cpu_ram(provisioner, soft_assert, provider, prov_data, vm_name):
    """ Tests change RAM and CPU in provisioning dialog.

    Prerequisities:
        * A provider set up, supporting provisioning in CFME

    Steps:
        * Open the provisioning dialog.
        * Apart from the usual provisioning settings, set number of CPUs and amount of RAM.
        * Submit the provisioning request and wait for it to finish.
        * Visit the page of the provisioned VM. The summary should state correct values for CPU&RAM.

    Metadata:
        test_flag: provision
    """
    prov_data["vm_name"] = vm_name
    if provider.type == "scvmm" and current_version() == "5.6":
        prov_data["num_cpus"] = "4"
    else:
        prov_data["num_sockets"] = "4"
        prov_data["cores_per_socket"] = "1" if provider.type != "scvmm" else None
    prov_data["memory"] = "4096"
    template_name = provider.data['provisioning']['template']
    vm = provisioner(template_name, prov_data)

    # Go to the VM info
    data = vm.get_detail(properties=("Properties", "Container")).strip()
    # No longer possible to use version pick because of cherrypicking?
    regexes = map(re.compile, [
        r"^[^(]*(\d+) CPUs?.*, ([^)]+)[^)]*$",
        r"^[^(]*\((\d+) CPUs?, ([^)]+)\)[^)]*$",
        r"^.*?(\d+) CPUs? .*?(\d+ MB)$"])
    for regex in regexes:
        match = regex.match(data)
        if match is not None:
            num_cpus, memory = match.groups()
            break
    else:
        raise ValueError("Could not parse string {}".format(repr(data)))
    soft_assert(num_cpus == "4", "num_cpus should be {}, is {}".format("4", num_cpus))
    soft_assert(memory == "4096 MB", "memory should be {}, is {}".format("4096 MB", memory))


# Special parametrization in testgen above
@pytest.mark.meta(blockers=[1209847, 1380782])
@pytest.mark.parametrize("disk_format", ["thin", "thick", "preallocated"])
@pytest.mark.uncollectif(lambda provider, disk_format:
                         (provider.type == "rhevm" and disk_format == "thick") or
                         (provider.type != "rhevm" and disk_format == "preallocated") or
                         # Temporarily, our storage domain cannot handle preallocated disks
                         (provider.type == "rhevm" and disk_format == "preallocated") or
                         (provider.type == "scvmm") or
                         (provider.key == "vsphere55" and disk_format == "thick"))
def test_disk_format_select(provisioner, disk_format, provider, prov_data, vm_name):
    """ Tests disk format selection in provisioning dialog.

    Prerequisities:
        * A provider set up, supporting provisioning in CFME

    Steps:
        * Open the provisioning dialog.
        * Apart from the usual provisioning settings, set the disk format to be thick or thin.
        * Submit the provisioning request and wait for it to finish.
        * Visit the page of the provisioned VM.
        * The ``Thin Provisioning Used`` field should state true of false according to the selection

    Metadata:
        test_flag: provision
    """
    prov_data["vm_name"] = vm_name
    prov_data["disk_format"] = disk_format
    template_name = provider.data['provisioning']['template']

    vm = provisioner(template_name, prov_data)

    # Go to the VM info
    vm.load_details(refresh=True)
    thin = InfoBlock.text(
        "Datastore Allocation Summary", "Thin Provisioning Used").strip().lower() == "true"
    if disk_format == "thin":
        assert thin, "The disk format should be Thin"
    else:
        assert not thin, "The disk format should not be Thin"


@pytest.mark.parametrize("started", [True, False])
def test_power_on_or_off_after_provision(provisioner, prov_data, provider, started, vm_name):
    """ Tests setting the desired power state after provisioning.

    Prerequisities:
        * A provider set up, supporting provisioning in CFME

    Steps:
        * Open the provisioning dialog.
        * Apart from the usual provisioning settings, set whether you want or not the VM to be
            powered on after provisioning.
        * Submit the provisioning request and wait for it to finish.
        * The VM should become steady in the desired VM power state.

    Metadata:
        test_flag: provision
    """
    prov_data["vm_name"] = vm_name
    prov_data["power_on"] = started
    template_name = provider.data['provisioning']['template']

    provisioner(template_name, prov_data)

    wait_for(
        lambda: provider.mgmt.does_vm_exist(vm_name) and
        (provider.mgmt.is_vm_running if started else provider.mgmt.is_vm_stopped)(vm_name),
        num_sec=240, delay=5
    )


def test_tag(provisioner, prov_data, provider, vm_name):
    """ Tests tagging VMs using provisioning dialogs.

    Prerequisities:
        * A provider set up, supporting provisioning in CFME

    Steps:
        * Open the provisioning dialog.
        * Apart from the usual provisioning settings, pick a tag.
        * Submit the provisioning request and wait for it to finish.
        * Visit th page of VM, it should display the selected tags


    Metadata:
        test_flag: provision
    """
    prov_data["vm_name"] = vm_name
    prov_data["apply_tags"] = [(["Service Level *", "Gold"], True)]
    template_name = provider.data['provisioning']['template']

    vm = provisioner(template_name, prov_data)

    tags = vm.get_tags()
    assert any(tag.category.display_name == "Service Level" and tag.display_name == "Gold"
               for tag in tags), "Service Level: Gold not in tags ({})".format(str(tags))


@pytest.mark.meta(blockers=[1204115])
def test_provisioning_schedule(provisioner, provider, prov_data, vm_name):
    """ Tests provision scheduling.

    Prerequisities:
        * A provider set up, supporting provisioning in CFME

    Steps:
        * Open the provisioning dialog.
        * Apart from the usual provisioning settings, set a scheduled provision and pick a time.
        * Submit the provisioning request, it should not start before the scheduled time.

    Metadata:
        test_flag: provision
    """
    now = datetime.utcnow()
    prov_data["vm_name"] = vm_name
    prov_data["schedule_type"] = "schedule"
    prov_data["provision_date"] = now.strftime("%m/%d/%Y")
    STEP = 5
    minutes_diff = (STEP - (now.minute % STEP))
    # To have some gap for automation
    if minutes_diff <= 3:
        minutes_diff += 5
    provision_time = timedelta(minutes=minutes_diff) + now
    prov_data["provision_start_hour"] = str(provision_time.hour)
    prov_data["provision_start_min"] = str(provision_time.minute)

    template_name = provider.data['provisioning']['template']

    provisioner(template_name, prov_data, delayed=provision_time)
