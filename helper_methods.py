import os, re, requests, paramiko, subprocess
import ipaddress, scapy.all, netifaces
import pandas as pd
from bs4 import BeautifulSoup


ipv4_regex = '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
ipv6_regex = ('(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:'
              '[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:'
              '[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}'
              '(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)'
              '|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}'
              '[0-9]){0,1}[0-9])\\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:'
              '((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))')


def is_ipv6(ip):
    if re.search(ipv6_regex, ip):
        return True
    return False


def extract_table_from_html(url):
    data = BeautifulSoup(requests.get(url).content, 'html.parser')

    table_header, table_data, tables = [], [], data.body.find_all("table")
    for table in tables:
        cols = table.find_all('th')
        for col in cols:
            table_header.append(col.get_text())
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            cols = [ele.text.strip() for ele in cols]
            table_data.append([ele for ele in cols if ele])

    return pd.DataFrame(table_data, columns=table_header)


def execute_remote_command(client_ip, client_user, key_path, command):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(client_ip, username=client_user, port=22, key_filename=key_path)
    ssh.exec_command(command)
    return ssh


def get_ip(interface):
    return netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr']


# as present in the Wehe server source code
def get_anonymizedIP(ip):
    ip_address = ipaddress.ip_address(ip)

    if ip_address.version == 4:
        mask = ipaddress.ip_address('255.255.255.0')  # /24 mask
        anonymizedIP = str(ipaddress.ip_address(int(ip_address) & int(mask)))
    elif ip_address.version == 6:
        mask = ipaddress.ip_address('ffff:ffff:ffff:0000:0000:0000:0000:0000')  # /48
        anonymizedIP = str(ipaddress.ip_address(int(ip_address) & int(mask)))
    else:
        anonymizedIP = ip

    return anonymizedIP


class Tcpdump(object):

    def __init__(self, dump_path=None, interface=None):
        self._interface = interface
        self._running = False
        self._p = None
        self.bufferSize = 131072
        self.dump_path = dump_path

    def start(self, ports=None):
        command = ['sudo', 'tcpdump', '-w', self.dump_path]

        if self._interface is not None:
            command += ['-i', self._interface]

        if ports is not None:
            for i, port in enumerate(ports):
                if i > 0: command += ['or']
                command += ['port', port]

        self._p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        '''
            Wait for tcpdump process to start listening for traffic by invoking self._p.stderr.readline()
        '''
        self._p.stderr.readline()
        self._running = True

        return ' '.join(command)

    def stop(self):
        output = ['-1', '-1', '-1']
        try:
            self._p.terminate()
            output = self._p.communicate()
        except AttributeError:
            return 'None'
        self._running = False
        return output

    def status(self):
        return self._running

    def clean_pcap(self, target_pcap, ip_to_anonymize):
        interim_pcap = "temp.pcap"
        os.system('sudo editcap -C 200:10000 {} {}'.format(self.dump_path, interim_pcap))
        os.system('sudo tcprewrite --fixcsum --pnat=[{}]:[{}] --infile={} --outfile={}'.format(
            ip_to_anonymize, get_anonymizedIP(ip_to_anonymize), interim_pcap, target_pcap
        ))

        # remove unused pcap file
        os.system('sudo rm {}'.format(self.dump_path))
        os.system('sudo rm {}'.format(interim_pcap))
