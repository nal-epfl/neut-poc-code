"""
by: Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python3 replayBackground.py --server --server_ip=0.0.0.0  --protocol=tcp
    python3 replayBackground.py --kill_server --protocol=tcp
    python3 replayBackground.py --client --trace_file=traces/link_0_trace_5.csv --server_ip=0.0.0.0 --protocol=tcp
    python3 replayBackground.py --multi_clients --traces_dir=./traces --server_ip=0.0.0.0 --protocol=tcp
    python3 replayBackground.py --select_background --in_dir=./dir1 --out_dir=./traces --sample_ratio=0.3 --prefix=link
    python3 replayBackground.py --unpack_background --back_dir=./dir1 --link_idx=0
"""

import random, socket, shutil, os, sched, time, argparse, paramiko, glob
import pandas as pd
import numpy as np
from multiprocessing import Process

SERVER_PORT = 1234


def run_server(server_ip='0.0.0.0', protocol='tcp'):
    if protocol == 'tcp': run_tcp_server(server_ip)
    run_udp_server(server_ip)


def run_udp_server(server_ip='0.0.0.0'):
    print('Start a UDP server')
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind((server_ip, SERVER_PORT))

    client_addresses, client_count = [], 0
    while (True):
        data, address = server.recvfrom(4096)
        if address not in client_addresses:
            client_addresses.append(address)
            client_count = client_count + 1
            print("Server received packet from new client: ({}, {}, {})".format(client_count, *address))
        if not data: break
    server.close()


def run_tcp_server(server_ip='0.0.0.0'):
    print('Start a TCP server')
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((server_ip, SERVER_PORT))
    server.listen(10000)
    while True:
        connection, address = server.accept()
        Process(target=accept_connection, kwargs={'connection': connection, 'address': address}).start()


def accept_connection(connection, address):
    print('Server accepted a connection from {}'.format(address))
    while True:
        data = connection.recv(4096)
        if not data: break
    connection.close()


def kill_server():
    try:
        if os.system('sudo lsof -t -i:{} > /dev/null 2>&1'.format(SERVER_PORT)) == 0:
            os.system('sudo kill -9 $(lsof -t -i:{})'.format(SERVER_PORT))
        time.sleep(10) # wait for tcp to close all the connections
        os.system(f'sudo lsof -i :{SERVER_PORT} | xargs sudo kill -9')
    except Exception as e:
        print('NO RUNNING SERVER')


def run_client(trace_file, server_ip='0.0.0.0', protocol='tcp'):
    if not ('.csv' in trace_file):
        print('trace must be a .csv file')
        return

    df = pd.read_csv(trace_file, names=['id', 'time', 'payload_size'], index_col=0)

    time.sleep(df['time'].values[0])
    print('Start a client running trace {}'.format(trace_file))

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM if protocol == 'tcp' else socket.SOCK_DGRAM)
    client_socket.connect((server_ip, SERVER_PORT))

    send_scheduler = sched.scheduler(time.time, time.sleep)
    for idx, event in df.iterrows():
        send_scheduler.enter(event.time, 1, client_socket.send, argument=(np.random.bytes(event.payload_size),))

    send_scheduler.run()
    client_socket.close()


def run_multi_clients(traces_dir, server_ip='0.0.0.0', protocol='tcp'):
    processes = []
    for trace_name in os.listdir(traces_dir):
        try:
            processes.append(Process(target=run_client, kwargs={
                'trace_file': '{}/{}'.format(traces_dir, trace_name), 'server_ip': server_ip, 'protocol': protocol
            }))
        except Exception as e:
            print('Failed to run client for trace {}: {}'.format(trace_name, e))

    # kick them off
    for process in processes:
        process.start()

    # now wait for them to finish
    for process in processes:
        process.join()


def execute_remote_command(client_ip, client_user, key_path, command):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(client_ip, username=client_user, port=22, key_filename=key_path)
    ssh.exec_command(command)
    return ssh


class RemoteBackClient:

    def __init__(self, client_info):
        self.info = client_info

    def sample_caida_back_from(self, back_dir, sample_ratio):
        sub_back_dir = '{}_sample_{}'.format(back_dir, sample_ratio)
        command = 'cd {}; rm -r {}; mkdir -p {}'.format(self.info['path'], sub_back_dir, sub_back_dir)
        execute_remote_command(self.info['ip'], self.info['user'], self.info['key_path'], command)

        for tag in ['link0', 'link1']:
            command = (
                'cd {}; '
                'python3 replayBackground.py --select_background '
                '--in_dir=./{}/{}/TCP --out_dir=./{} --sample_ratio={} --prefix={}'.format(
                    self.info['path'], back_dir, tag, sub_back_dir, sample_ratio, tag
                ))
            execute_remote_command(self.info['ip'], self.info['user'], self.info['key_path'], command)
        return sub_back_dir

    def start_replay(self, background_dir, server_ip, protocol):
        command = (
            'ulimit -n 1048576 && '
            'cd {} && '
            'python3 replayBackground.py --multi_clients --traces_dir=./{}{} --server_ip={} --protocol={}'.format(
                self.info['path'], background_dir, self.info["dirs_suffix"], server_ip, protocol)
        )
        execute_remote_command(self.info['ip'], self.info['user'], self.info['key_path'], command)

    def kill_all_clients(self):
        command = 'kill -9 $(ps ax | grep \'replayBackground.py\' | awk \'{print $1}\')'
        execute_remote_command(self.info['ip'], self.info['user'], self.info['key_path'], command)


def select_background(in_dir, out_dir, prefix, sample_ratio=0.3):
    traces_name = os.listdir(in_dir)
    for trace in random.sample(list(traces_name), int(sample_ratio * len(traces_name))):
        shutil.copyfile('{}/{}'.format(in_dir, trace), '{}/{}_{}'.format(out_dir, prefix, trace))
        

def unpack_link_traces(back_dir, link_idx):
    for tar_file in glob.glob(f'{back_dir}/*.tar.gz'):
        os.system('cd {}; tar -xzvf {}'.format(back_dir, tar_file.split('/')[-1]))
        for dir_name in glob.glob('{}/*'.format(tar_file.replace('.tar.gz', ''))):
            if f'link{link_idx}' not in dir_name: os.system(f'rm -r {dir_name}')


if __name__ == '__main__':

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--server', action='store_true')
    arg_parser.add_argument('--protocol', default='tcp')
    arg_parser.add_argument('--client', action='store_true')
    arg_parser.add_argument('--multi_clients', action='store_true')
    arg_parser.add_argument('--select_background', action='store_true')
    arg_parser.add_argument('--unpack_background', action='store_true')
    arg_parser.add_argument('--server_ip', default='0.0.0.0')
    arg_parser.add_argument('--trace_file')
    arg_parser.add_argument('--traces_dir')
    arg_parser.add_argument('--back_dir')
    arg_parser.add_argument('--in_dir')
    arg_parser.add_argument('--out_dir')
    arg_parser.add_argument('--sample_ratio', default=0.3)
    arg_parser.add_argument('--link_idx')
    arg_parser.add_argument('--prefix', default='')
    arg_parser.add_argument('--kill_server', action='store_true')
    args = arg_parser.parse_args()

    if args.server:
        run_server(args.server_ip, args.protocol)
    elif args.kill_server:
        kill_server()
    elif args.client:
        run_client(args.trace_file, args.server_ip, args.protocol)
    elif args.multi_clients:
        run_multi_clients(args.traces_dir, args.server_ip, args.protocol)
    elif args.select_background:
        select_background(args.in_dir, args.out_dir, args.prefix, float(args.sample_ratio))
    elif args.unpack_background:
        unpack_link_traces(args.back_dir, args.link_idx)
