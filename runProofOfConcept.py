"""
by: Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python runProofOfConcept.py --reset_tc --interface=eno1 --ifb=ifb0
    python runProofOfConcept.py --enable_policing --interface=eno1 --target_srcs=128.178.122.153/32 --rate=5mbit --burst=15000 --limit=15000 --ifb=ifb0
    python runProofOfConcept.py --run --app=youtube --interface=eno1 --rate=20mbit --burst=15000 --limit=15000 --background_traces=traces
    python runProofOfConcept.py --run --auto_config --app=youtube --interface=eno1 --rate=20mbit --limit_as_ratio=0.75 --background_traces=traces

Note:
    the rule of thumb to set the burst = rate(mbit) * rtt(sec) * 125000
"""
import argparse, time, itertools

import numpy as np

from IOPaths import *
from td_module import *
from exp_module import *

NET_INTERFACE = 'eno1'

app_volumes = {
    'meet': 1, 'probemeet': 1,
    'webex': 2, 'probewebex': 2, 'probe2webex': 2, 'incprobewebex': 2,
    'zoom': 2.5, 'probezoom': 2.5,
    'whatsapp': 4, 'probewhatsapp': 4,
    'teams': 2, 'probeteams': 2,
    'skype': 3, 'probe1skype': 3, 'probe2skype': 3, 'incprobeskype': 3,
    'youtube': 22, 'disneyplus': 30, 'netflix': 13, 'amazon': 20, 'twitch': 30, 'hulu': 25,
    'facebookvideo': 18, 'nbcsports': 22, 'longtcp': 25
}
back_volume_by_pct = { '0.25': 25, '0.5': 55, '0.75': 85, '1': 105 }

def get_traffic_volume(app_name, background_pct):
    return app_volumes[app_name] + back_volume_by_pct[background_pct]


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
    arg_parser.add_argument('--run_exps', action='store_true')
    arg_parser.add_argument('--run_control_exps', action='store_true')
    args = arg_parser.parse_args()

    if args.reset_tc:
        reset_tc(args.interface)
    elif args.enable_policing:
        TCPolicer(
            args.target_srcs, args.interface, args.ifb, 
            PolicerConfig(rate=args.rate, use_burst_period=False, burst_param=args.burst, use_limit_ratio=False, limit_param=args.limit)
        ).enable_policing()
    elif args.run & args.auto_config:
        m_wehe_app = get_WeheApp(args.app)
        m_wehe_servers = MLabNearestWeheServers()
        m_policer_config = PolicerConfig(rate=args.rate, use_burst_period=False, burst_param=(20 * 1e-3), use_limit_ratio=True, limit_param=args.limit_as_ratio)        
        
        poc_exp = POCExp(m_wehe_app, m_wehe_servers, None, args.interface, 'results')
        poc_exp.set_common_policer(m_policer_config)
        poc_exp.run()
    elif args.run:
        m_wehe_app = get_WeheApp(args.app)
        m_wehe_servers = MLabNearestWeheServers()
        m_policer_config = PolicerConfig(rate=args.rate, use_burst_period=False, burst_param=args.burst, use_limit_ratio=False, limit_param=args.limit)
        
        poc_exp = POCExp(m_wehe_app, m_wehe_servers, None, args.interface, 'results')
        poc_exp.set_common_policer(m_policer_config)
        poc_exp.run()
    elif args.run_control_exps:
        m_interface = NET_INTERFACE

        m_tested_apps = [
            WeheApp.longtcp, WeheApp.youtube, WeheApp.disneyplus, WeheApp.netflix, WeheApp.amazon, WeheApp.twitch,
            WeheApp.skype, WeheApp.whatsapp, WeheApp.teams, WeheApp.zoom, WeheApp.webex,
        ]
        
        # other parameters
        m_results_dir = 'results_imc23_control_new'

        for m_app in m_tested_apps:
            reset_tc(m_interface)
            m_wehe_servers = CustomWeheServers()

            try:
                poc_exp = POCExp(m_app, m_wehe_servers, None, m_interface, m_results_dir)
                poc_exp.run()
                print('\n-------------------------------------\n')
                time.sleep(120)
            except Exception as e:
                print(e, '\n-------------------------------------\n')
                time.sleep(300)
    elif args.run_exps:
        m_interface = NET_INTERFACE
        
        # the background servers
        m_back_servers = ['icnals18, icnals19']
        m_background_dirs = ['chicago_2010_back_traffic_5min_control_cbp_2links_v{}'.format(i) for i in np.arange(2, 7)]
        m_back_sample_ratio = 0.5
        
        # the policer configurations
        m_burst_period, m_rate_ratios, m_limit_ratios = 0.035, [1.3, 1.5, 2, 2.5], [0.25, 0.5, 1]
        m_common_policer = True

        # the applications
        m_tested_apps = [WeheApp.youtube, WeheApp.disneyplus, WeheApp.netflix, WeheApp.amazon, WeheApp.twitch]
        
        # other parameters
        m_results_dir = 'results_sigcomm_tcp'

        # run the applications
        nb_run = 0
        for m_back_dir, m_rate_ratio, m_limit_ratio in itertools.product(m_background_dirs, m_rate_ratios, m_limit_ratios):
            for m_app in m_tested_apps:

                nb_run = nb_run + 1
                print('Run number: ', nb_run)

                # clean before start
                reset_tc(m_interface)                

                try:
                    m_wehe_servers = MLabNearestWeheServers()
                    m_back_replay = BackgroundReplay(m_interface, m_app.value['protocol'], m_back_servers, m_back_dir, traffic_ratio=m_back_sample_ratio)
                    poc_exp = POCExp(m_app, m_wehe_servers, m_back_replay, m_interface, m_results_dir)
                    
                    # configure the policer
                    m_rate = PolicerConfig.get_rate(m_rate_ratio, get_traffic_volume(m_app, str(m_back_sample_ratio)))
                    if m_common_policer:
                        m_policer_config = PolicerConfig(rate='{}mbit'.format(m_rate), use_burst_period=True, burst_param=m_burst_period, use_limit_ratio=True, limit_param=m_limit_ratio)
                        poc_exp.set_common_policer(m_policer_config)
                    else:
                        m_policer_config = PolicerConfig(rate='{}mbit'.format(m_rate/2), use_burst_period=True, burst_param=m_burst_period, use_limit_ratio=True, limit_param=m_limit_ratio)
                        poc_exp.set_noncommon_policers(m_policer_config)

                    poc_exp.run()
                    print('\n-------------------------------------\n')
                    time.sleep(120)
                except Exception as e:
                    print(e, '\n-------------------------------------\n')
                    time.sleep(300)


