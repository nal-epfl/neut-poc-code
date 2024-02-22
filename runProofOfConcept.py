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
import multiprocessing
import shutil

import argparse, socket, time
import json, itertools
from multiprocessing import Process

from IOPaths import *
from td_module import *
import background_replay.replayBackground as backReplay
import test_downloads.downloadTests as testDownloader

udp_wehe_apps = {'meet', 'teams', 'skype', 'twittervideo', 'webex', 'whatsapp', 'zoom'}
tcp_wehe_apps = {
    'youtube', 'netflix', 'twitch', 'hulu', 'spotify', 'disneyplus', 'facebookvideo', 'dailymotion', 'deezer',
    'nbcsports', 'molotovtv', 'mycanal', 'ocs', 'amazon', 'salto', 'sfrplay', 'vimeo', 'longtcp'
}
wehe_ports = ['443', '3480', '8801', '9000', '19305', '3478', '49882']

app_volumes = {
    'meet': 1, 'probemeet': 1,
    'webex': 2, 'probewebex': 2, 'probe2webex': 1, 'incprobewebex': 2,
    'zoom': 2.5, 'probezoom': 2,
    'whatsapp': 4, 'probewhatsapp': 2,
    'teams': 2, 'probeteams': 2,
    'skype': 3, 'probe1skype': 3, 'probe2skype': 3, 'incprobeskype': 3,

    # 'youtube': 22, 'disneyplus': 42, 'netflix': 15, 'amazon': 20, 'twitch': 50, 'hulu': 25,
    # 'facebookvideo': 18, 'nbcsports': 22, 'longtcp': 25
    'youtube': 25, 'disneyplus': 30, 'netflix': 25, 'amazon': 25, 'twitch': 30, 'hulu': 25,
    'facebookvideo': 18, 'nbcsports': 22, 'longtcp': 25
}
# back_volume_by_pct = {
#     '0': 0, '0.25': 25, '0.5': 50, '0.75': 85, '1': 105
# }

back_volume_by_pct = {
    '0': 0, '0.25': 25, '0.5': 55, '0.75': 85, '1': 105
}


def get_traffic_volume(app_name, background_pct):
    return app_volumes[app_name] + back_volume_by_pct[background_pct]


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
    return servers_ips


def get_custom_servers():
    with open(os.path.join(WEHE_CMDLINE_DIR, 'res/servers_ip_list.txt'), 'r') as f:
        return ['{}/32'.format(ip.rstrip('\n')) for ip in f.readlines()]


def load_wehe_cmdline_keys(keys_dir):
    shutil.copy(os.path.join(WEHE_CMDLINE_DIR, 'res', keys_dir, 'main'), os.path.join(WEHE_CMDLINE_DIR, 'res'))
    shutil.copy(os.path.join(WEHE_CMDLINE_DIR, 'res', keys_dir, 'metadata'), os.path.join(WEHE_CMDLINE_DIR, 'res'))


def get_background_server(server_name):
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'background_replay/clients_info.json'), 'r') as f:
        return '{}/32'.format(json.load(f)[server_name]['ip'])


def get_back_clients(servers_names):
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'clients_info.json'), 'r') as f:
        clients_info = json.load(f)
        return [backReplay.RemoteBackClient(clients_info[s]) for s in servers_names]


def start_background_server(interface, protocol='tcp'):
    server_ip = get_ip(interface)
    print('Start background server with ip={}'.format(server_ip))
    backReplay.run_server(server_ip=server_ip, protocol=protocol)


def flush_replay_background(back_servers):
    # kill any background process if exists
    for process in multiprocessing.active_children(): process.kill()

    # kill background server on this machine if it exists
    backReplay.kill_server()

    # kill all clients on the remote machine
    for back_server in back_servers:
        back_server.kill_all_clients()


def run_wehe_test(wehe_app, use_custom_servers=True, results_dir='results'):
    os.chdir(WEHE_CMDLINE_DIR)
    command = ['java', '-jar', 'wehe-cmdline.jar']
    if use_custom_servers: command += ['-s', 'custom']
    command += ['-n', wehe_app, '-c', '-r', '{}/'.format(results_dir), '-l', 'info', '-u', '2']
    subprocess.run(command, timeout=300)
    os.chdir('..')


class POCExp:

    def __init__(self, wehe_app, wehe_servers, back_clients, eth_interface, result_dir):
        # app info
        self.wehe_app = wehe_app
        self.app_protocol = 'tcp' if wehe_app in tcp_wehe_apps else 'udp'
        # the servers runing wehe
        self.wehe_servers = wehe_servers
        self.use_custom_servers = True
        # the servers running background traffic
        self.back_clients = back_clients
        self.back_dir = ''
        self.warmup_time = 10
        # the incoming traffic interface (for policing)
        self.eth_interface = eth_interface
        self.ip = get_ip(self.eth_interface)
        self.tc_policers = []
        self.policing_info = {'policer_type': -1, 'rate:': -1, 'burst': -1, 'limit': -1}
        # results directory for wehe-cmdline-tomo
        self.result_dir = result_dir
        os.makedirs(os.path.join(WEHE_CMDLINE_DIR, self.result_dir), exist_ok=True)

    def use_mlab(self):
        self.use_custom_servers = False
        load_wehe_cmdline_keys('mlab_keys')

    def use_custom_server(self):
        self.use_custom_servers = True
        load_wehe_cmdline_keys('custom_keys')

    def set_tc_policer(self, tc_policer):
        rate, burst, limit = tc_policer.get_tbf_params()
        self.tc_policers = [tc_policer]
        self.policing_info = {'policer': {'type': 'common', 'rate': '{}mbit'.format(rate), 'burst': burst, 'limit': limit}}

    def set_common_policer(self, rate, burst_period, limit_ratio):
        burst = TCPolicer.get_burst(rate, burst_period)
        limit = TCPolicer.get_limit(burst, limit_ratio)
        senders = np.concatenate([['{}/32'.format(b.info['ip']) for b in self.back_clients], self.wehe_servers])
        self.tc_policers = [TCPolicer(senders, self.eth_interface, 'ifb0', '{}mbit'.format(rate), burst, limit)]
        self.policing_info = {'policer': {'type': 'common', 'rate': '{}mbit'.format(rate), 'burst': burst, 'limit': limit}}

    def set_noncommon_policers(self, rate, burst_period, limit_ratio):
        burst = TCPolicer.get_burst(rate, burst_period)
        limit = TCPolicer.get_limit(burst, limit_ratio)
        p1_senders = np.array(['{}/32'.format(self.back_clients[0].info['ip']), self.wehe_servers[0]])
        p2_senders = np.array(['{}/32'.format(self.back_clients[1].info['ip']), self.wehe_servers[1]])
        self.tc_policers = [
            TCPolicer(p1_senders, self.eth_interface, 'ifb0', '{}mbit'.format(rate), burst, limit, traffic_tag=100),
            TCPolicer(p2_senders, self.eth_interface, 'ifb1', '{}mbit'.format(rate), burst, limit, traffic_tag=200)
        ]
        self.policing_info = {'policer': {'type': 'non-common', 'rate': '{}mbit'.format(rate), 'burst': burst, 'limit': limit}}

    def set_different_policers(self, rates, burst_period, limit_ratio):
        p1_senders = np.array(['{}/32'.format(self.back_clients[0].info['ip']), self.wehe_servers[0]])
        p1_burst = TCPolicer.get_burst(rates[0], burst_period)
        p1_limit = TCPolicer.get_limit(p1_burst, limit_ratio)
        p1_policer = TCPolicer(p1_senders, self.eth_interface, 'ifb0', '{}mbit'.format(rates[0]), p1_burst, p1_limit, traffic_tag=100)

        p2_senders = np.array([self.wehe_servers[1]])
        p2_burst = TCPolicer.get_burst(rates[1], burst_period)
        p2_limit = TCPolicer.get_limit(p2_burst, limit_ratio)
        p2_policer = TCPolicer(p2_senders, self.eth_interface, 'ifb1', '{}mbit'.format(rates[1]), p2_burst, p2_limit, traffic_tag=200)

        self.tc_policers = [p2_policer, p1_policer]
        self.policing_info = {'policer': { 'type': 'different',
            'rate': ['{}mbit'.format(r) for r in rates], 'burst': [p1_burst, p2_burst], 'limit': [p1_limit, p2_limit],
        }}


    def set_client_back_replay(self, back_dir):
        self.back_dir = back_dir

    def select_client_back_replay_sample(self, back_dir, sample_ratio):
        for back_client in self.back_clients:
            self.back_dir = back_client.sample_caida_back_from(back_dir, sample_ratio)

    def run(self):
        # start the policer
        for tc_policer in self.tc_policers:
            tc_policer.enable_policing()

        # start background server
        back_process = Process(
            target=start_background_server, kwargs={'interface': self.eth_interface, 'protocol': self.app_protocol})
        back_process.start()
        print('Background server is running.')
        print('Do not forget to start the background client replays. Wehe CLI test will start in 1 min.')

        # start background client on the remote machine
        for back_client in self.back_clients:
            back_client.start_replay(self.back_dir, self.ip, self.app_protocol)
        time.sleep(self.warmup_time)

        # try to run the wehe app
        try:
            # start tcpdump from client side
            if self.app_protocol == 'udp':
                for tc_policer in self.tc_policers:
                    tc_policer.start_tcpdump(os.path.join(WEHE_CMDLINE_DIR, self.result_dir), wehe_ports)

            # start the wehe cli test
            run_wehe_test(wehe_app=self.wehe_app, use_custom_servers=self.use_custom_servers, results_dir=self.result_dir)

            # collect and save info
            wehe_info = testDownloader.get_run_test_info(os.path.join(WEHE_CMDLINE_DIR, self.result_dir))
            test_info = {**wehe_info, 'app': self.wehe_app, **self.policing_info, 'background': self.back_dir}

            output_dir = '{}/{}'.format(TESTS_INFO_DIR, test_info['date'].replace('/', '-'))
            test_file_info = 'test_{}_{}_info.json'.format(test_info['user_id'], test_info['test_id'])
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, test_file_info), 'w') as f:
                json.dump(test_info, f)

            # clean everything
            flush_replay_background(self.back_clients)
            reset_tc(interface=self.eth_interface)

            # save and clean pcaps
            for tc_policer in self.tc_policers:
                tc_policer.stop_tcpdump(output_dir, '{}_{}'.format(test_info['user_id'], test_info['test_id']))
        except Exception as e:
            flush_replay_background(self.back_clients)
            reset_tc(interface=self.eth_interface)
            print('failed to record policer configuration because of: ', e)


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
    arg_parser.add_argument('--run_exp', action='store_true')
    arg_parser.add_argument('--run_control_exp', action='store_true')
    args = arg_parser.parse_args()

    if args.reset_tc:
        reset_tc(args.interface)
    elif args.enable_policing:
        TCPolicer(args.target_srcs, args.interface, args.ifb, args.rate, args.burst, args.limit).enable_policing()
    elif args.run & args.auto_config:
        m_rate = float(re.findall("\d+\.?\d+", args.rate)[0])
        poc_exp = POCExp(args.app, get_custom_servers(), get_back_clients(['icnals17']), args.interface, 'results')
        poc_exp.set_common_policer(m_rate, (20 * 1e-3), args.limit_as_ratio)
        poc_exp.set_client_back_replay(args.background_traces)
        poc_exp.run()
    elif args.run:
        poc_exp = POCExp(args.app, get_custom_servers(), get_back_clients(['icnals17']), args.interface, 'results')
        poc_exp.set_tc_policer(TCPolicer(args.target_srcs, args.interface, args.ifb, args.rate, args.burst, args.limit))
        poc_exp.set_client_back_replay(args.background_traces)
        poc_exp.run()
    elif args.run_control_exp:
        m_interface = 'eno1'

        # the background servers
        m_back_clients = get_back_clients([])#'icnals18', 'icnals19'])
        m_background_dirs = ['imc_back_v{}'.format(i) for i in np.arange(1, 2)]
        back_sample_ratio = 0.5

        m_tested_apps = [
            #'longtcp', 'youtube', 'disneyplus', 'netflix', 'amazon', 'twitch',
            #'skype', 'whatsapp', 'teams', 'zoom', 'webex',
            'probe2skype', 'probewhatsapp', #'probeteams', 'probezoom', 'probe2webex'
        ]

        for m_back_dir, m_app in itertools.product(m_background_dirs, m_tested_apps):
            # clean before start
            reset_tc(m_interface)
            flush_replay_background(m_back_clients)

            # get wehe servers
            m_wehe_servers = get_custom_servers()

            try:
                results_dir = 'results_imc23_control_new'
                poc_exp = POCExp(m_app, m_wehe_servers, m_back_clients, m_interface, results_dir)
                poc_exp.use_custom_server()
                # poc_exp.select_client_back_replay_sample(m_back_dir, back_sample_ratio)
                poc_exp.run()
                print('\n-------------------------------------\n')
                time.sleep(120)
            except Exception as e:
                print(e, '\n-------------------------------------\n')
                time.sleep(300)

    elif args.run_exp:
        m_interface = 'eno1'

        # the background servers
        m_back_clients = get_back_clients(['icnals18', 'icnals19'])
        m_background_dirs = ['imc_back_v{}'.format(i) for i in np.arange(1, 2)]
        back_sample_ratio = 0.5

        # the policer configurations
        m_burst_period, m_rate_ratios, m_limit_ratios = 0.03, [1.3, 1.5, 2, 2.5], [0.25, 0.5, 1]

        # the applications
        m_apps = [
            'longtcp', 'youtube', 'disneyplus', 'netflix', 'amazon', 'twitch',
            'skype', 'whatsapp', 'teams', 'zoom', 'webex',
            'probe2skype', 'probewhatsapp', 'probeteams', 'probezoom', 'probe2webex'
        ]
        m_tested_apps = ['longtcp']

        # run the applications
        nb_run = 0
        for m_back_dir, m_rate_ratio, m_limit_ratio in itertools.product(m_background_dirs, m_rate_ratios, m_limit_ratios):
            for m_app in m_tested_apps:

                nb_run = nb_run + 1
                print('Run number: ', nb_run)

                # clean before start
                reset_tc(m_interface)
                flush_replay_background(m_back_clients)

                # get wehe servers
                m_wehe_servers = get_custom_servers()
                # m_wehe_servers = list(get_all_mlab_servers().values())

                try:
                    results_dir = 'results_imc23_common_longtcp'
                    poc_exp = POCExp(m_app, m_wehe_servers, m_back_clients, m_interface, results_dir)
                    poc_exp.use_custom_server()

                    m_rate = TCPolicer.get_rate(m_rate_ratio, get_traffic_volume(m_app, str(back_sample_ratio)))
                    print(m_app, m_rate_ratio, m_rate, m_limit_ratio)
                    poc_exp.set_common_policer(m_rate, m_burst_period, m_limit_ratio)
                    # poc_exp.set_noncommon_policers(m_rate / 2, m_burst_period, m_limit_ratio)

                    poc_exp.select_client_back_replay_sample(m_back_dir, back_sample_ratio)
                    poc_exp.run()
                    print('\n-------------------------------------\n')
                    time.sleep(120)
                except Exception as e:
                    print(e, '\n-------------------------------------\n')
                    time.sleep(300)


