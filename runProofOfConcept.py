"""
by: Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python runProofOfConcept.py --reset_tc --interface=enp0s31f6 --ifb=ifb0
    python runProofOfConcept.py --enable_policing --interface=enp0s31f6 --target_srcs=128.178.122.153/32 --rate=5mbit --burst=1500 --limit=1500 --ifb=ifb0
    python runProofOfConcept.py --run --app=youtube --interface=eno1 --rate=20mbit --burst=1500 --limit=1500 --background_traces=traces
    python runProofOfConcept.py --run --auto_config --app=youtube --interface=eno1 --rate=20mbit --limit_as_ratio=0.75 --background_traces=traces

Note:
    the rule of thumb to set the burst = rate(mbit) * rtt(sec) * 125000
"""

import numpy as np
import argparse, requests, os, socket, netifaces, time, subprocess
import re, json
from multiprocessing import Process

from IOPaths import *
from helper_methods import *
import background_replay.replayBackground as backReplay
import test_downloads.downloadTests as testDownloader

udp_wehe_apps = {"meet", "teams", "skype", "twittervideo", "webex", "whatsapp", "zoom"}
tcp_wehe_apps = {
    "youtube", "netflix", "twitch", "hulu", "spotify", "disneyplus", "facebookvideo", "dailymotion", "deezer",
    "nbcsports", "molotovtv", "mycanal", "ocs", "amazon", "salto", "sfrplay", "vimeo"
}
wehe_apps = {"skype"}


# as present in the Wehe server source code
def get_anonymizedIP(ip):
    if "." in ip:
        v4ExceptLast = ip.rsplit('.', 1)[0]
        anonymizedIP = v4ExceptLast + '.0'
    elif ":" in ip:
        v6ExceptLast = ip.rsplit(':', 1)[0]
        anonymizedIP = v6ExceptLast + ':0000'
    else:
        anonymizedIP = ip

    return anonymizedIP


def get_nearest_mlab_servers():
    print('Fetch Nearest M-Lab servers')
    data = requests.get('https://locate.measurementlab.net/v2/nearest/wehe/replay').json()
    servers = [record['machine'] for record in data['results']]
    servers_ips = {s: '{}/24'.format(socket.gethostbyname(s)) for s in servers}
    return servers_ips


def get_all_mlab_servers():
    print('Fetch All M-Lab servers')
    mlab_servers_df = extract_table_from_html('https://locate.measurementlab.net/admin/sites')
    servers_ips = {}
    for server_id in mlab_servers_df['Site ID']:
        for mlabi in ['mlab1', 'mlab2', 'mlab3', 'mlab4']:
            try:
                server_name = '{}-{}.mlab-oti.measurement-lab.org'.format(mlabi, server_id)

                ipv4 = socket.getaddrinfo(server_name, None, socket.AF_INET)[0][4][0]
                servers_ips['{}_ipv4'.format(server_name)] = '{}/24'.format(ipv4)

                ipv6 = socket.getaddrinfo(server_name, None, socket.AF_INET6)[0][4][0]
                servers_ips['{}_ipv6'.format(server_name)] = '{}/64'.format(ipv6)
            except Exception as e:
                continue
    with open("mlab_servers.json", "w") as write_file:
        json.dump(servers_ips, write_file, indent=4)
    return servers_ips


def get_epfl_servers():
    with open(os.path.join(WEHE_CMDLINE_DIR, 'res/servers_ip_list.txt'), 'r') as f:
        return ['{}/32'.format(ip.rstrip('\n')) for ip in f.readlines()]


def get_background_server():
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'client_info.json'), 'r') as f:
        return '{}/32'.format(json.load(f)['ip'])


def get_ip(interface):
    return netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr']


def reset_tc(interface, ifb='ifb0'):
    print('Remove current tc stuff')
    os.system('sudo tc qdisc del dev {} root'.format(interface))
    os.system('sudo tc qdisc del dev {} handle ffff: ingress'.format(interface))
    os.system('sudo modprobe -r ifb')


def enable_policing(interface, target_srcs, rate, burst, limit=15000, ifb='ifb0'):
    reset_tc(interface=interface, ifb=ifb)

    # create the ifb interface
    os.system('sudo modprobe ifb')
    os.system('sudo ifconfig {} up'.format(ifb))
    os.system('sudo ifconfig {} txqueuelen 1'.format(ifb))

    # forward inbound traffic to ifb
    os.system('sudo tc qdisc add dev {} root fq maxrate 10gbit'.format(interface))
    os.system('sudo tc qdisc add dev {} handle ffff: ingress'.format(interface))
    for i, src in enumerate(target_srcs):
        os.system(
            'sudo tc filter add dev {} parent ffff: protocol all u32 '
            'match ip{} src {} '
            'action mirred egress redirect dev {} '
            'action drop '.format(interface, '6' if is_ipv6(src) else '', src, ifb)
        )

    os.system('sudo tc qdisc add dev {} root handle 1: tbf rate {} burst {} limit {}'.format(ifb, rate, burst, limit))

    # os.system('sudo tc qdisc add dev {} root handle 1: netem delay 34ms limit 30'.format(ifb))
    # os.system('sudo tc qdisc add dev {} parent 1:1 handle 10: tbf rate {} burst {} limit {}'.format(ifb, rate, burst, limit))

    print('Policing is now enabled. Do not forget to --reset_tc when you are done.')


def start_background_server(interface):
    server_ip = get_ip(interface)
    print('Start background server with ip={}'.format(server_ip))
    backReplay.run_server(server_ip=server_ip)


def run_wehe_test(wehe_app):
    os.chdir(WEHE_CMDLINE_DIR)
    os.system('java -jar wehe-cmdline.jar -s epfl -n {} -c -r results/ -l info -u 2'.format(wehe_app))
    os.chdir('..')
    return testDownloader.get_run_test_info('{}/results'.format(WEHE_CMDLINE_DIR))


def run_proof_of_concept(wehe_app, interface, with_policing, rate, burst, limit, background_dir='traces'):
    # enable policing
    senders = np.concatenate([[get_background_server()], get_epfl_servers()]) # list(get_all_mlab_servers().values())])
    if with_policing:
        enable_policing(interface=interface, target_srcs=senders, rate=rate, burst=burst, limit=limit)

    # start background server
    back_process = Process(target=start_background_server, kwargs={'interface': interface})
    back_process.start()
    print('Background server is running.')
    print('Do not forget to start the background client replays. Wehe CLI test will start in 1 min.')

    # start background client on the remote machine
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'client_info.json'), 'r') as f:
        client_info = json.load(f)
        command = ('cd {} && ''python3 replayBackground.py --multi_clients --traces_dir=./{} --server_ip={}'.format(
            client_info['path'], background_dir, get_ip(interface)
        ))
        execute_remote_command(client_info['ip'], client_info['user'], client_info['pass'], command)

    # sleep for warmup
    time.sleep(10)

    try:
        # start tcpdump from client side
        temp_pcap = '{}/results/tcpdump_out.pcap'.format(WEHE_CMDLINE_DIR)
        command = ['sudo', 'tcpdump', '-w', temp_pcap, '-i', 'ifb0', 'port', '3478', 'or', 'port', '443']
        tcpdump_p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tcpdump_p.stderr.readline()

        # start the wehe cli test
        test_info = run_wehe_test(wehe_app=wehe_app)

        # save the test information
        test_info['background'] = background_dir
        test_info['rate'], test_info['burst'], test_info['limit'], test_info['app'] = rate, burst, limit, wehe_app
        output_dir = '{}/{}'.format(TESTS_INFO_DIR, test_info['date'].replace('/', '-'))
        os.makedirs(output_dir, exist_ok=True)
        with open('{}/test_{}_{}_info.json'.format(output_dir, test_info['user_id'], test_info['test_id']), 'w') as f:
            json.dump(test_info, f)

        # stop and copy tcpdump output
        out_pcap = '{}/dump_{}_{}.pcap'.format(output_dir, test_info['user_id'], test_info['test_id'])
        os.system('sudo tcprewrite --fixcsum --pnat=[{}]:[{}] --infile={} --outfile={}'.format(
            get_ip(interface), get_anonymizedIP(get_ip(interface)), temp_pcap, out_pcap
        ))
        os.system('sudo rm {}'.format(temp_pcap))
    except Exception as e:
        print('failed to record policer configuration because of: ', e)
    finally:
        # stop the client at the server
        command = 'kill -9 $(ps ax | grep \'replayBackground.py --multi_clients\' | awk \'{print $1}\')'
        execute_remote_command(client_info['ip'], client_info['user'], client_info['pass'], command)

        # clean everything
        back_process.kill()
        reset_tc(interface=interface)


if __name__ == '__main__':

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--reset_tc', action='store_true')
    arg_parser.add_argument('--enable_policing', action='store_true')
    arg_parser.add_argument('--run', action='store_true')
    arg_parser.add_argument('--auto_config', action='store_true')
    arg_parser.add_argument('--interface')
    arg_parser.add_argument('--ifb', default='ifb0')
    arg_parser.add_argument('--target_srcs', action='append', type=str)
    arg_parser.add_argument('--rate')
    arg_parser.add_argument('--burst')
    arg_parser.add_argument('--limit')
    arg_parser.add_argument('--limit_as_ratio')
    arg_parser.add_argument('--app')
    arg_parser.add_argument('--background_traces', default='traces')
    args = arg_parser.parse_args()

    if args.reset_tc:
        reset_tc(args.interface, args.ifb)
    elif args.enable_policing:
        enable_policing(args.interface, args.target_srcs, args.rate, args.burst, args.limit, args.ifb)
    elif args.run & args.auto_config:
        rate = float(re.findall("\d+\.?\d+", args.rate)[0])
        burst = int(rate * (20 * 1e-3) * 125000)
        limit = int(burst * float(args.limit_as_ratio))
        run_proof_of_concept(args.app, args.interface, True, args.rate, burst, limit, args.background_traces)
    elif args.run:
        run_proof_of_concept(args.app, args.interface, True, args.rate, args.burst, args.limit, args.background_traces)
