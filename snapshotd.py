#!/usr/bin/env python3
"""
Network Device Config Collector
Supports SSH CLI commands and NETCONF get-config
Concurrent execution with YAML device inventory
"""
import signal
import os
import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import yaml
import paramiko
from ncclient import manager

shutdown_flag = False

def signal_handler(sig, frame):
    global shutdown_flag
    print("\n\nSIGINT received. Shutting down gracefully...")
    shutdown_flag = True
    exit()

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)

def parse_yaml_devices():
    """Parse devices.yaml into device list"""
    yaml_path = Path('devices.yaml')
    if not yaml_path.exists():
        print("ERROR: devices.yaml not found!")
        print("Create devices.yaml with this format:")
        print("""
devices:
  - name: device1
    ip: 192.168.1.10
    username: admin
    password: cisco123
    port: 22
    method: ssh
    command: "show running-config"
  - name: device2
    ip: 192.168.1.11
    username: admin
    password: cisco123
    port: 830
    method: netconf
""")
        sys.exit(1)
    
    with open(yaml_path) as f:
        config = yaml.safe_load(f)
    
    devices = config.get('devices', [])
    if not devices:
        print("ERROR: No 'devices' list found in YAML!")
        sys.exit(1)
    
    print(f"Loaded {len(devices)} devices from devices.yaml")
    return devices

def ssh_collect(device):
    """SSH execution with paramiko"""
    output_dir = Path(f"output/{device['name']}")
    output_dir.mkdir(exist_ok=True)
    
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        print(f"[{device['name']}] Connecting SSH {device['ip']}:{device['port']}...")
        client.connect(
            device['ip'], 
            port=device['port'], 
            username=device['username'], 
            password=device['password'], 
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
        
        stdin, stdout, stderr = client.exec_command(device['command'])
        output = stdout.read().decode('utf-8', errors='ignore') + stderr.read().decode('utf-8', errors='ignore')
        
        timestamp = time.strftime("%d%m%Y_%H%M%S")
        filename = output_dir / f"{device['name']}_ssh_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Device: {device['name']} ({device['ip']}:{device['port']})\n")
            f.write(f"# Method: SSH\n")
            f.write(f"# Command: {device['command']}\n")
            f.write(f"# Collected: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Output length: {len(output)} bytes\n\n")
            f.write(output)
        
        print(f"[{device['name']}]  Saved {len(output)} bytes to {filename}")
        client.close()
        
    except Exception as e:
        print(f"[{device['name']}]  SSH Error: {str(e)}")

def netconf_collect(device):
    """NETCONF get-config with ncclient"""
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    
    try:
        print(f"[{device['name']}] Connecting NETCONF {device['ip']}:{device['port']}...")
        
        with manager.connect(
            host=device['ip'],
            port=device['port'],
            username=device['username'],
            password=device['password'],
            hostkey_verify=False,
            timeout=30,
            device_params={'name':'default'}  # Generic device
        ) as m:
            
            config = m.get_config(source='running')
        
        timestamp = int(time.time())
        filename = output_dir / f"{device['name']}_netconf_{timestamp}.xml"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"<!-- Device: {device['name']} ({device['ip']}:{device['port']}) -->\n")
            f.write(f"<!-- Method: NETCONF -->\n")
            f.write(f"<!-- Collected: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n")
            f.write(f"<!-- Size: {len(config.xml)} bytes -->\n\n")
            f.write(config.xml)
        
        print(f"[{device['name']}] ✓ Saved NETCONF config ({len(config.xml)} bytes) to {filename}")
        
    except Exception as e:
        print(f"[{device['name']}] ✗ NETCONF Error: {str(e)}")

def device_worker(device):
    name = device['name']
    interval = int(device.get('interval', 3600))
    print(f"[{name}] Scheduler started, interval={interval}s")

    while not shutdown_flag:
        if shutdown_flag:
            print(f"[{name}] Shutdown requested, exiting worker")
            break

        try:
            method = device['method'].lower()
            if method == 'ssh':
                ssh_collect(device)
            elif method == 'netconf':
                netconf_collect(device)
        except Exception as e:
            print(f"[{name}] Error: {e}")
        
        # Sleep with periodic checks (interruptible every 1s)
        for _ in range(interval):
            if shutdown_flag:
                print(f"[{name}] Interrupt during sleep, exiting")
                return
            time.sleep(1)
    print(f"[{name}] Worker stopped")


def main():
    """Main execution"""
    print("Network Device Config Collector (scheduled mode)")
    print("=" * 60)

    devices = parse_yaml_devices()
    if not devices:
        return

    print(f"\nStarting schedulers for {len(devices)} devices...")
    print("Each device runs in its own thread with its own interval.\n")

    with ThreadPoolExecutor(max_workers=len(devices)) as executor:
        # Start one long‑running worker per device
        for device in devices:
            executor.submit(device_worker, device)

        # Keep main thread alive (workers run forever)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping schedulers, exiting...")


if __name__ == "__main__":
    main()
