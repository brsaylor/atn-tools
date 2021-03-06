#!/usr/bin/env python3

"""
Ben Saylor
November 2015, January 2016

Process a set of biomass data files (ATN*.csv) - one file per simulation -
create a summary CSV file with one row per simulation with various features
calculated from the biomass data.

FIXME: update description
"""

import sys
import os.path
import gzip
import csv
from math import log2
import re
import glob

import numpy as np
from scipy import stats, signal
import pandas as pd
import h5py

from .nodeconfigs import parse_node_config, node_config_to_params
from .simulationdata import SimulationData, EXTINCT
from . import util, foodwebs


def get_sim_number(filename):
    """
    Based on a filename such as
    ATN.csv
    ATN_1.csv
    ATN_123.csv
    return the simulation number such as
    0
    1
    123
    """
    match = re.match(r'.+_(\d+)\..+', filename)
    return int(match.group(1)) if match else 0


def get_species_data(filename=None):
    """
    Given the filename of the CSV containing species-level data (for all
    species, rows unique by nodeId),
    return a dict whose keys are node IDs and keys are dicts containing the data
    for that species.
    """

    if filename is None:
        filename = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                'data/species-data.csv')

    data = {}
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[int(row['nodeId'])] = {
                'name': row['name'],
                'trophicLevel': float(row['trophicLevel'])
            }
    return data


def get_simulation_data(filename):
    """ Read simulation output data from a CSV or HDF5 file """

    if filename.endswith('.h5'):
        return get_simulation_data_hdf5(filename)

    with (gzip.open(filename, 'rt') if filename.endswith('gz')
            else open(filename, 'r')) as f:
        if f.readline().startswith('Job_id'):
            f.seek(0)
            return get_simulation_data_sim_csv_format(f)
        else:
            f.seek(0)
            return get_simulation_data_atn_csv_format(f)


def rmse(df1, df2):
    """ Calculate the root mean squared error between the two DataFrames and
    return as a Series indexed by node ID. The sum of this series is the score
    for an attempt in the Convergence game. """
    return np.sqrt(((df1 - df2) ** 2).mean())


def environment_score(species_data, node_config, biomass_data):
    """
    Compute the original Environment Score for all timesteps for the given data and
    return the score time series.  The calculations are taken from
    model.Ecosystem.updateEcosystemScore() in WoB_Server.
    """
    # FIXME: remove species_data argument

    node_config_dict = {n['nodeId']: n for n in node_config}

    # 1-D Arrays of per_unit_biomass and trophic_level, lined up to the columns in the dataframe
    per_unit_biomass = np.array([node_config_dict[node_id]['perUnitBiomass'] for node_id in biomass_data.columns])

    serengeti = foodwebs.get_serengeti()
    trophic_level = np.array([serengeti.node[node_id]['trophic_level'] for node_id in biomass_data.columns])

    clipped_biomass = np.array(biomass_data).clip(0)
    num_species = (clipped_biomass > 0).sum(axis=1)
    species_scores = per_unit_biomass * ((clipped_biomass / per_unit_biomass) ** trophic_level)
    scores = species_scores.sum(axis=1)
    with np.errstate(divide='ignore'):  # Ignore divide-by-zero; we handle the resulting -inf by clipping
        scores = (np.round(np.log2(scores)) * 5.0).clip(0)
    scores = np.round(scores ** 2 + num_species ** 2)

    return scores


def environment_score_slope(simdata, skip=0):
    """ Return the linear regression slope of the original WoB environment score,
    excluding the initial `skip` timesteps of data. """
    parsed_node_config = parse_node_config(simdata.node_config)
    scores = environment_score(None, parsed_node_config, simdata.biomass[skip:])
    slope = stats.linregress(
        simdata.biomass.index[skip:],
        scores)[0]
    return slope


def total_biomass(speciesData, node_config, biomass_data):
    """
    Return a time series of the total biomass of all species
    """
    num_timesteps = len(biomass_data[node_config[0]['nodeId']])
    total_biomass = np.empty(num_timesteps)
    for timestep in range(num_timesteps):
        total_biomass[timestep] = sum(
                [biomass[timestep] for biomass in biomass_data.values()])
    return total_biomass


def net_production(species_data, node_config, biomass_data):
    """
    Time-series measure of ecosystem health
    computed as net production (change/derivative in total biomass)
    """
    B = total_biomass(species_data, node_config, biomass_data)
    net_prod = B - np.roll(B, 1)
    
    # Can't really say that net production was equal to total biomass at t0
    net_prod[0] = net_prod[-1] = 0
    
    return net_prod


def shannon_index_biomass_product(species_data, node_config, biomass_data):
    """
    Time-series measure of ecosystem health
    computed as the product of the Shannon index (based on biomass)
    and the total biomass.
    """
    num_timesteps = len(biomass_data[node_config[0]['nodeId']])
    scores = np.zeros(num_timesteps)
    
    for timestep in range(num_timesteps):
        species_biomass = np.empty(len(node_config))
        for i, node in enumerate(node_config):
            species_biomass[i] = max(0, biomass_data[node['nodeId']][timestep])
        total_biomass = species_biomass.sum()
        for i, node in enumerate(node_config):
            if species_biomass[i] <= 0:
                continue
            proportion = species_biomass[i] / total_biomass
            scores[timestep] -= proportion * log2(proportion)
        scores[timestep] *= total_biomass
    
    return scores


def shannon_index_biomass_product_norm(species_data, node_config, biomass_data):
    """
    A version of shannonIndexBiomassProduct normalized by initial total biomass
    and maximum possible Shannon index for the number of species,
    enabling more meaningful comparison across ecosystems of different sizes.
    """

    total_initial_biomass = sum(
            [biomass[0] for biomass in biomass_data.values()])
    perfect_shannon = 0
    for i, node in enumerate(node_config):
        proportion = 1 / len(node_config)
        perfect_shannon -= proportion * log2(proportion)
    return (shannon_index_biomass_product(species_data, node_config, biomass_data)
            / (total_initial_biomass * perfect_shannon))


def last_nonzero_timestep(biomass_data):
    """
    Returns the last timestep at which there is nonzero biomass.
    """
    df = biomass_data
    nonzero = pd.Series(index=df.index, data=False)
    for col in df:
        nonzero |= (df[col] != 0)
    return nonzero.sort_index(ascending=False).argmax()


def get_output_attributes(simdata, species_data, optional_output_attributes=[]):
    """
    Given a SimulationData object and species data as returned by get_species_data,
    return a dictionary of attributes whose keys are
    "<attribute_name>_<node_id>" for species-specific attributes and
    "<attribute_name>"          for non-species-specific attributes
    """
    # FIXME: remove species_data argument

    out = {
        'timesteps_simulated': simdata.timesteps_simulated,
        'stop_event': simdata.stop_event,
        'extinction_count': simdata.extinction_count,
    }

    for node_id in simdata.node_ids:
        out['extinction_{}'.format(node_id)] = simdata.extinction_timesteps[node_id]

    if optional_output_attributes is None:
        optional_output_attributes = []
    if 'environment_score_slope' in optional_output_attributes:
        out['environment_score_slope'] = environment_score_slope(simdata)
    elif 'environment_score_slope_skip200' in optional_output_attributes:
        out['environment_score_slope_skip200'] = environment_score_slope(simdata, skip=200)

    return out


def generate_summary_file(set_number, batch_number, output_file, biomass_files,
                          optional_output_attributes=[]):
    species_data = get_species_data()

    outfile = None
    writer = None

    for sim_number, infilename in sorted(
            [(get_sim_number(f), f) for f in biomass_files]):

        print("\rprocessing simulation: {}".format(sim_number), end='', flush=True)

        # if sim_number % 100 == 0:
        #     print(sim_number, end='', flush=True)
        # elif sim_number % 20 == 0:
        #     print('.', end='', flush=True)

        # Create the output row from the simulation identifiers, input and
        # output attributes
        outrow = {}
        identifiers = {
            'set_number': set_number,
            'batch_number': batch_number,
            'sim_number': sim_number,
        }
        outrow.update(identifiers)
        simdata = SimulationData(infilename)
        node_config_list = parse_node_config(simdata.node_config)
        input_attributes = node_config_to_params(node_config_list)
        biomass_data = simdata.biomass
        outrow.update(input_attributes)
        output_attributes = get_output_attributes(simdata, species_data,
                                                  optional_output_attributes)
        outrow.update(output_attributes)

        if writer is None:
            # Set up the CSV writer

            fieldnames = (
                sorted(identifiers.keys()) +
                sorted(input_attributes.keys()) +
                sorted(output_attributes.keys()))
            outfile = open(output_file, 'w')
            writer = csv.DictWriter(outfile, fieldnames)
            writer.writeheader()

        writer.writerow(outrow)

    print()

    if outfile is not None:
        outfile.close()


def generate_summary_file_for_batch(set_number, batch_number, optional_output_attributes=[]):
    set_dir = util.find_set_dir(set_number)
    if set_dir is None:
        print("Error: set {} not found".format(set_number), file=sys.stderr)
        return None
    batch_dir = util.find_batch_dir(set_dir, batch_number)
    if batch_dir is None:
        print(
            "Error: set {} does not contain batch {}".format(set_number, batch_number),
            file=sys.stderr)
        return None
    generate_summary_file(
        set_number,
        batch_number,
        os.path.join(batch_dir, 'summary.csv'),
        glob.iglob(os.path.join(batch_dir, 'biomass-data/*.h5')),
        optional_output_attributes)
