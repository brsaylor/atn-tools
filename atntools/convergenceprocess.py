"""
Automation for generating simulations for Convergence
"""

import os
import glob
import re
import logging
import copy
from collections import OrderedDict, Counter
import json
import pprint

import matplotlib.pyplot as plt

from atntools import settings, util, simulation, nodeconfigs, foodwebs, plotting

MAX_TIMESTEPS = 100000


def run_sequence(food_web, initial_metaparameter_template, cvg_metaparameter_template):

    sequence_num, sequence_dir = create_sequence_dir()

    log_filename = os.path.join(sequence_dir, 'log.txt')
    print("Logging to " + log_filename)
    logging.basicConfig(filename=log_filename, level=logging.INFO)
    logging.getLogger().addHandler(logging.StreamHandler())

    logging.info("Created sequence dir {}".format(sequence_dir))
    logging.info("Food web: {}".format(food_web))

    #
    # Initial set
    #

    initial_set, initial_set_dir = util.create_set_dir(food_web, initial_metaparameter_template)
    logging.info("Created initial set {}".format(initial_set))

    logging.info("Simulating initial batch, not saving biomass data")
    initial_batch = simulation.simulate_batch(
        initial_set, MAX_TIMESTEPS, no_record_biomass=True)
    print()

    #
    # Sustaining set
    #

    cvg_timesteps = cvg_metaparameter_template['args']['timesteps_to_analyze']

    sustaining_metaparameter_template = {
        'generator': 'filter-sustaining',
        'args': {
            'input_dir': os.path.join(
                util.find_batch_dir(initial_set_dir, initial_batch),
                'biomass-data')
        }
    }
    sustaining_set, sustaining_set_dir = util.create_set_dir(
        food_web, sustaining_metaparameter_template)
    logging.info("Created sustaining set {}".format(sustaining_set))

    logging.info("Simulating sustaining batch to steady state, saving biomass data")
    sustaining_batch = simulation.simulate_batch(sustaining_set, MAX_TIMESTEPS)
    print()

    #
    # Convergence set
    #

    cvg_metaparameter_template = copy.deepcopy(cvg_metaparameter_template)
    cvg_metaparameter_template['args']['input_set'] = sustaining_set
    cvg_metaparameter_template['args']['input_batch'] = sustaining_batch
    cvg_set, cvg_set_dir = util.create_set_dir(food_web, cvg_metaparameter_template)
    logging.info("Created convergence set {}".format(cvg_set))

    logging.info("Simulating convergence batch, saving {} timesteps of biomass data"
                 .format(cvg_timesteps))
    cvg_batch = simulation.simulate_batch(
        cvg_set, cvg_timesteps, no_stop_on_steady_state=True)
    print()

    sequence_info = OrderedDict([
        ('food_web', food_web),
        ('initial_set', initial_set),
        ('initial_batch', initial_batch),
        ('sustaining_set', sustaining_set),
        ('sustaining_batch', sustaining_batch),
        ('cvg_set', cvg_set),
        ('cvg_batch', cvg_batch),
    ])
    with open(os.path.join(sequence_dir, 'sequence-info.json'), 'w') as f:
        json.dump(sequence_info, f, indent=4)

    logging.info("Done.")


def compile_data(sequence_numbers, output_dir):
    """ Compile the convergence data from cvg-sequence-n
    for each n in sequence_numbers
    and put it in output_dir (which must not already exist). """

    sim_count_by_food_web = Counter()
    sim_count_by_food_web_size = Counter()

    # Create the top-level directory to hold the data
    try:
        os.makedirs(output_dir)
    except OSError:
        print("Error: output directory already exists: {}".format(
            output_dir), file=sys.stderr)
        return

    log_filename = os.path.join(output_dir, 'log.txt')
    print("Logging to " + log_filename)
    logging.basicConfig(filename=log_filename, level=logging.INFO)
    logging.getLogger().addHandler(logging.StreamHandler())

    for sequence_dir in map(get_sequence_dir, sequence_numbers):

        logging.info("Processing " + sequence_dir)

        # Load the sequence info, skipping if incomplete
        try:
            with open(os.path.join(sequence_dir, 'sequence-info.json')) as f:
                sequence_info = json.load(f)
        except FileNotFoundError:
            continue

        # Locate the data produced by filter-convergence
        set_num = sequence_info['cvg_set']
        batch_num = sequence_info['cvg_batch']
        batch_dir = util.find_batch_dir(set_num, batch_num)

        # Open the node configs
        with open(os.path.join(batch_dir, 'node-configs.txt')) as f:
            node_configs = f.readlines()

        for original_sim_number, node_config in enumerate(node_configs):
            node_config = node_config.strip()

            # Identify the food web formed by the surviving species
            node_ids = node_ids_from_node_config(node_config)
            num_species = len(node_ids)
            food_web_id = '-'.join(map(str, node_ids))

            # Determine the new sim number
            # by counting the number of simulations found for this food web
            new_sim_number = sim_count_by_food_web[food_web_id]
            sim_count_by_food_web[food_web_id] += 1
            sim_count_by_food_web_size[len(node_ids)] += 1

            # Initialize the food web directory, if it hasn't been
            cvg_food_web_dir = os.path.join(
                output_dir,
                '{}-species'.format(num_species),
                food_web_id)
            if not os.path.isdir(cvg_food_web_dir):
                init_food_web_dir(cvg_food_web_dir, node_ids)

            # Append the current node config to the new node config file
            with open(os.path.join(cvg_food_web_dir, 'node-configs.txt'), 'a') as f:
                print(node_config, file=f)

            # Make a symbolic link pointing to the data file
            original_datafile = os.path.join(
                batch_dir, 'biomass-data',
                simdata_filename(original_sim_number))
            new_datafile = os.path.join(
                cvg_food_web_dir, 'biomass-data',
                simdata_filename(new_sim_number))
            os.symlink(original_datafile, new_datafile)

            # Generate a plot
            plotting.plot_biomass_data(
                new_datafile,
                None,
                title='{} #{}'.format(food_web_id, new_sim_number),
                ylim=(0, None),
                show_legend=True,
                output_file=os.path.join(
                    cvg_food_web_dir, 'biomass-plots',
                    plot_filename(new_sim_number)),
                output_dpi=80)

    logging.info("\nSimulation count by food web:")
    logging.info('\n' + pprint.pformat(dict(sim_count_by_food_web)))
    logging.info("\nSimulation count by food web size:")
    logging.info('\n' + pprint.pformat(dict(sim_count_by_food_web_size)))
    logging.info("\n{} distinct food webs".format(len(sim_count_by_food_web)))
    logging.info("{} simulations total".format(sum(sim_count_by_food_web.values())))


def create_sequence_dir():
    sequence_num = get_max_sequence_number() + 1
    sequence_dir = get_sequence_dir(sequence_num)
    os.makedirs(sequence_dir)
    return sequence_num, sequence_dir


def get_max_sequence_number():
    max_sequence_number = -1
    for sequence_dir in list_sequence_dirs():
        match = re.match(r'.+?/cvg-sequence-(\d+)', sequence_dir)
        if match is None:
            continue
        sequence_num = int(match.group(1))
        if sequence_num > max_sequence_number:
            max_sequence_number = sequence_num
    return max_sequence_number


def get_sequence_dir(sequence_number):
    return os.path.join(settings.DATA_HOME, 'sequences/cvg-sequence-{}'.format(sequence_number))


def list_sequence_dirs():
    return glob.iglob(os.path.join(settings.DATA_HOME, 'sequences/cvg-sequence-*'))


def node_ids_from_node_config(node_config):
    nodes = nodeconfigs.parse_node_config(node_config)
    node_ids = [node['nodeId'] for node in nodes]
    node_ids.sort()
    return node_ids


def init_food_web_dir(food_web_dir, node_ids):
    biomass_dir = os.path.join(food_web_dir, 'biomass-data')
    os.makedirs(biomass_dir, exist_ok=True)
    for datafile in glob.iglob(os.path.join(biomass_dir, '*.h5')):
        os.remove(datafile)

    plot_dir = os.path.join(food_web_dir, 'biomass-plots')
    os.makedirs(plot_dir, exist_ok=True)
    for plotfile in glob.iglob(os.path.join(biomass_dir, '*.png')):
        os.remove(plotfile)

    # Create empty node config file (emptying any existing file)
    open(os.path.join(food_web_dir, 'node-configs.txt'), 'w').close()

    serengeti = foodwebs.get_serengeti()
    subweb = serengeti.subgraph(node_ids)
    food_web_id = '-'.join(map(str, node_ids))
    plt.figure()
    foodwebs.draw_food_web(
        subweb,
        show_legend=True,
        output_file=os.path.join(food_web_dir, 'foodweb.{}.png'.format(food_web_id)))

    with open(os.path.join(food_web_dir, 'foodweb.{}.json'.format(food_web_id)), 'w') as f:
        print(foodwebs.food_web_json(subweb), file=f)


def simdata_filename(sim_number):
    return 'ATN.h5' if sim_number == 0 else 'ATN_{}.h5'.format(sim_number)


def plot_filename(sim_number):
    return 'ATN.png' if sim_number == 0 else 'ATN_{}.png'.format(sim_number)
