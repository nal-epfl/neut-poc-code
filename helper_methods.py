import os, re, requests, paramiko
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


def execute_remote_command(client_ip, client_user, client_password, command):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    ssh.connect(client_ip, username=client_user, password=client_password, port=22)
    ssh.exec_command(command)
    return ssh