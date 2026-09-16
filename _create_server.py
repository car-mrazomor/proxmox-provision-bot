import requests
import json

import random
import string

import urllib3
import os
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
data_config = json.loads(open("data_config.json", "r").read())
server_config = data_config["api"]["server_info"]

storage_name = "local"
image_path = "/var/lib/vz/template/iso/"

def mnt_unmnt(node, vmid, _type="mnt", iso="systemrescue-12.02-amd64.iso"):
    proxmox_ip = server_config[node]["proxmox_ip"]
    username = server_config[node]["username"]
    password = server_config[node]["password"]

    auth_url = f"https://{proxmox_ip}:8006/api2/json/access/ticket"
    auth_data = {"username":username, "password":password}
    response = requests.post(auth_url, data=auth_data, verify=False)
    ticket = response.json()["data"]["ticket"]
    csrf_token = response.json()["data"]["CSRFPreventionToken"]
    headers = {"CSRFPreventionToken":csrf_token}
    cookies = {"PVEAuthCookie":ticket}

    current_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/config"

    if _type == "mnt":
        current_data = {"ide0":f"local:iso/{iso},media=cdrom"}
        res = requests.post(current_url, data=current_data, cookies=cookies, headers=headers, verify=False)
        current_data = {"boot":"order=ide0;virtio0;ide2;net0"}
        res = requests.post(current_url, data=current_data, cookies=cookies, headers=headers, verify=False)
        return res
    elif _type == "unmnt":
        current_data = {"delete":"ide0"}
        res = requests.post(current_url, data=current_data, cookies=cookies, headers=headers, verify=False)
        current_data = {"boot":"order=virtio0;ide2;net0"}
        res = requests.post(current_url, data=current_data, cookies=cookies, headers=headers, verify=False)
        return res
    else:
        return False

def create_server_api(ios, server_name, node, ssh_key=None, storage=25, cpu=1, ram=2):
    proxmox_ip = server_config[node]["proxmox_ip"]
    username = server_config[node]["username"]
    password = server_config[node]["password"]
    isos = data_config["isos"]
    template = isos[ios] if "iso_" not in ios else isos["rocky-10"]
    full_path = os.path.join(image_path, template)
    root_password = "".join(random.choice(string.ascii_letters+string.digits) for _ in range(12))
    cpu_cores = cpu
    memory_mb = int(ram) * 1024
    disk_size = f"{storage}G"

    auth_url = f"https://{proxmox_ip}:8006/api2/json/access/ticket"
    auth_data = {"username":username, "password":password}
    response = requests.post(auth_url, data=auth_data, verify=False)
    ticket = response.json()["data"]["ticket"]
    csrf_token = response.json()["data"]["CSRFPreventionToken"]
    headers = {"CSRFPreventionToken":csrf_token}
    cookies = {"PVEAuthCookie":ticket}

    next_vmid_url = f"https://{proxmox_ip}:8006/api2/json/cluster/nextid"
    next_vmid = {"vmid":random.randint(100, 9999)}
    
    while True:
        response = requests.get(next_vmid_url, headers=headers, cookies=cookies, params=next_vmid, verify=False)
        if response.status_code != 200:
            next_vmid ["vmid"] += 1
            continue
        vmid = response.json()["data"]
        break
    
    if "windows" in ios:
        create_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{template}/clone"
        create_vm_data = {
            "newid":vmid,
            "name":server_name,
            "target":node,
            "full":"1",
            "storage":"local",
            "format":"qcow2"
        }
        headers = {"CSRFPreventionToken":csrf_token}
        cookies = {"PVEAuthCookie":ticket}
        response = requests.post(create_vm_url, data=create_vm_data, headers=headers, cookies=cookies, verify=False)

        create_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/config"
        create_vm_data = {"memory":memory_mb, "cores":cpu_cores,}
        headers = {"CSRFPreventionToken":csrf_token}
        cookies = {"PVEAuthCookie":ticket}
        response = requests.post(create_vm_url, data=create_vm_data, headers=headers, cookies=cookies, verify=False)

    else:
        create_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu"
        create_vm_data = {
            "name":f"{server_name}",
            "memory":memory_mb,
            "cores":cpu_cores,
            "vmid":vmid,
            "net0":"virtio,bridge=vmbr0",
            "virtio0":f"{storage_name}:0,import-from={full_path},format=qcow2",
            "ipconfig0":"ip=dhcp",
            "serial0":"socket",
            "vga":"virtio,memory=256",
            "ide2":"local:cloudinit",
            "cicustom":"user=local:snippets/user-data.yaml",
            "agent":"1",
            "cpu": "host",
            "nameserver":"8.8.8.8 8.8.4.4",
        }
        
        if ios == "alpine":
            create_vm_data ["efidisk0"] = f"{storage_name}:0,efitype=4m,format=raw"
            create_vm_data ["bios"] = "ovmf"
            create_vm_data ["cicustom"] = f"user=local:snippets/a-data.yaml"

        if ios == "gentoo" or ios == "freebsd":
            create_vm_data ["efidisk0"] = f"{storage_name}:0,efitype=4m,format=raw"
            create_vm_data ["bios"] = "ovmf"
            create_vm_data ["cicustom"] = f"user=local:snippets/g-data.yaml" if ios == "gentoo" else f"user=local:snippets/bsd-data.yaml"

        headers = {"CSRFPreventionToken":csrf_token}
        cookies = {"PVEAuthCookie":ticket}
        response = requests.post(create_vm_url, data=create_vm_data, headers=headers, cookies=cookies, verify=False)

    resize_disk_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/resize"
    resize_disk_data = {
        "disk":"ide0" if "windows" in ios else "virtio0",
        "size":disk_size,
    }
    response = requests.put(resize_disk_url, data=resize_disk_data, headers=headers, cookies=cookies, verify=False)

    start_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/status/start"
    response = requests.post(start_vm_url, headers=headers, cookies=cookies, verify=False)

    while True:
        status_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/agent/ping"
        response = requests.post(status_url, headers=headers, cookies=cookies, verify=False)
        if response.status_code == 200:
            break
        
        time.sleep(5)

    time.sleep(10)

    get_ip_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"
    response = requests.get(get_ip_url, headers=headers, cookies=cookies, verify=False)
    
    interfaces = response.json()["data"]["result"]
    for iface in interfaces:
        for addr in iface.get("ip-addresses", []):
            ip = addr.get("ip-address", "")
            if "." in ip and not ip.startswith(("127.", "10.", "192.168.", "172.")):
                ip_address = ip
                break
        else:
            continue
        break

    change_password_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/agent/set-user-password"
    change_password_data = {
        "username": "root",
            "password": root_password,
    }
    response = requests.post(change_password_url, change_password_data, headers=headers, cookies=cookies, verify=False)

    if ssh_key:
        cmd = ("mkdir -p /root/.ssh && "
            "chmod 700 /root/.ssh && "
            "grep -qxF '{key}' /root/.ssh/authorized_keys || "
            "echo '{key}' >> /root/.ssh/authorized_keys && "
            "chmod 600 /root/.ssh/authorized_keys").format(key=ssh_key)

        data = {"command":["/bin/sh","-c",cmd]}
        add_ssh_key_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/agent/exec"
        response = requests.post(add_ssh_key_url, json=data, headers=headers, cookies=cookies, verify=False)

    def hrestart_server(server_id):
        start_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{server_id}/status/reboot"
        response = requests.post(start_vm_url, headers=headers, cookies=cookies, verify=False)
        return response.json()
    
    def reconfig(vmid, ip_address):
        create_vm_url = f"https://{proxmox_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/config"
        gateway_ip = ".".join(ip_address.split(".")[:3]) + ".1"
        create_vm_data = {"ipconfig0":f"ip={ip_address}/24,gw={gateway_ip}"}
        headers = {"CSRFPreventionToken":csrf_token}
        cookies = {"PVEAuthCookie":ticket}
        response = requests.post(create_vm_url, data=create_vm_data, headers=headers, cookies=cookies, verify=False)
        return response.json()
    
    reconfig(vmid, ip_address)

    if "iso_" in ios:
        iso = ios.split("iso_")[1].strip()
        iso = isos[iso]
        mnt_unmnt(node, vmid, _type="mnt", iso=iso)

    hrestart_server(vmid)
    time.sleep(15)

    if "iso_" in ios:
        return vmid, "", ip_address, node
    return vmid, root_password, ip_address, node