#!/usr/bin/env python3

import os
import csv
import random

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

from atntools.util import WOB_DB_DIR

def read_serengeti_from_csv():
    """
    Loads the Serengeti food web from CSV exports from the WoB database (the
    species and consume tables)
    """

    g = nx.DiGraph()

    f = open(os.path.join(WOB_DB_DIR, 'species-table.csv'))
    reader = csv.DictReader(f)
    for row in reader:
        g.add_node(int(row['species_id']), **row)
    f.close()

    f = open(os.path.join(WOB_DB_DIR, 'consume-table.csv'))
    reader = csv.DictReader(f)
    for row in reader:
        g.add_edge(int(row['prey_id']), int(row['species_id']))
    f.close()

    return g

def read_serengeti_from_graphml():
    return nx.readwrite.graphml.read_graphml('serengeti.graphml')

def read_serengeti(remove_isolated_species=True):
    
    # According to %timeit in Jupyter
    # read_serengeti_from_csv()
    # is faster than
    # read_serengeti_from_graphml()
    graph = read_serengeti_from_csv()

    if remove_isolated_species:
        # Remove isolated species from the full web
        graph.remove_nodes_from(
                [54, 58, 62, 78, 79, 81, 84, 1006, 1007, 1008, 1009])

    return graph

def read_species_table():
    # FIXME: Redundant; should read data from graph
    species_table = pd.read_csv(os.path.join(WOB_DB_DIR,
        'species-table.csv'), index_col='species_id')
    return species_table

def draw_food_web(graph, include_names=False, include_legend=False):
    """
    Note: Does not draw cannibalism loops
    """
    plt.figure()
    
    #pos = nx.spring_layout(graph)
    
    graphviz_prog = 'dot'
    #graphviz_prog = 'neato'
    pos = nx.drawing.nx_agraph.graphviz_layout(graph, prog=graphviz_prog, args='-Grankdir=BT')
    
    # Attempt at layout by trophic level. Doesn't work too well. Labels and edges overlap a lot.
    #pos = {}
    #count_by_trophic_level = {}
    #for node, data in graph.nodes_iter(data=True):
    #    trophic_level = float(data['trophic_level'])
    #    rounded_trophic_level = round(trophic_level)
    #    if rounded_trophic_level not in count_by_trophic_level:
    #        count_by_trophic_level[rounded_trophic_level] = 1
    #    else:
    #        count_by_trophic_level[rounded_trophic_level] += 1
    #    pos[node] = (count_by_trophic_level[rounded_trophic_level], trophic_level)
    # Using the positions calculated above as initial positions for spring_layout destroys the trophic-level-y
    #pos = nx.spring_layout(graph, pos=pos)
    
    # Instead, color nodes by trophic level.
    
    colors = [float(data['trophic_level']) * -1 + 5 for node, data in graph.nodes_iter(data=True)]
    
    nx.draw_networkx_nodes(graph, pos, node_color=colors, cmap='RdYlGn', vmin=1, vmax=4)
    #nx.draw_networkx_nodes(graph, pos, node_size=colors)
    nx.draw_networkx_edges(graph, pos)
    
    plt.gca().set_axis_bgcolor('white')
    
    if include_names:
        labels = {node[0]: '  ' + node[1]['species_id'] + ' ' + node[1]['name']
                    for node in graph.nodes(data=True)}
        
    else:
        labels = {node[0]: node[1]['species_id']
                    for node in graph.nodes(data=True)}
    nx.draw_networkx_labels(graph, pos, labels)
    
    # Draw images
    # Not working yet; try http://stackoverflow.com/questions/4860417/placing-custom-images-in-a-plot-window-as-custom-data-markers-or-to-annotate-t
    #img = mpimg.imread('images/Aardvark.png')
    
    cur_axes = plt.gca()
    cur_axes.axes.get_xaxis().set_visible(False)
    cur_axes.axes.get_yaxis().set_visible(False)
    
    #plt.axis('off')
    
    if include_legend:
        # FIXME: Read data from graph
        species_table = read_species_table()
        df = species_table[['name', 'trophic_level']]
        table_text = df.loc[graph.nodes()].sort_values('trophic_level', 0, False).to_string(
            formatters={'name': lambda s: '{:<31}'.format(s)},
            justify='left', col_space=0)
        
        # Manually add 1 character of padding around text
        # ('pad' in bbox arg below adds padding inside and outside border, interfering with alignment)
        table_text = '\n' + '\n'.join([' ' + line + ' '  for line in table_text.split('\n')]) + '\n'
        
        plt.text(plt.gca().get_xlim()[1] * 1.02, plt.gca().get_ylim()[1], table_text, family='monospace',
                bbox={'edgecolor': 'black', 'facecolor': 'white', 'pad': 0},
                verticalalignment='top')

def random_subgraph(graph, N):
    """
    Return a subgraph of 'graph' containing N nodes selected at random and all
    of the edges between them. Not very useful for small food sub-webs, because
    the nodes are usually disconnected.
    """
    nodes = random.sample(graph.nodes(), N)
    return graph.subgraph(nodes)

def get_source_nodes(graph, allow_selfloops=True):
    """
    Get the source nodes (nodes with no in-edges) of the given graph.  If
    allow_selfloops is True, a node whose only in-edge is a self-loop is also
    considered a source node.
    """
    source_nodes = []
    for node, in_degree in graph.in_degree_iter():
        if in_degree == 0:
            source_nodes.append(node)
    if allow_selfloops:
        for node, in_degree in graph.in_degree_iter(graph.nodes_with_selfloops()):
            if in_degree == 1:
                source_nodes.append(node)
    return source_nodes

def get_basal_species(graph):
    basal_species = []
    for species_id, species_attributes in graph.nodes_iter(data=True):
        if float(species_attributes['trophic_level']) == 1:
            basal_species.append(species_id)
    return basal_species

def get_plant_eaters(graph):
    """
    Return the set of nodes which have a source node as a predecessor.
    """
    plant_eaters = set()
    for plant in get_source_nodes(graph):
        for node in graph.successors(plant):
            plant_eaters.add(node)
    return plant_eaters

def predator_complete_subweb(G, N, seed_nodes=None, seed_size=1, retry=1):
    """
    A version of random_successor_subgraph with the following addition: Each
    iteration, before choosing a random neighbor, choose a neighbor of a plant
    eater which does not currently have a predator ("lonely plant eater") in the
    subgraph (if any).
    
    The goal is to produce a sub-web in which everything that eats plants has a
    predator, but this is not guaranteed, because:
    - Some plant eaters have no predators in the full graph
      (e.g. African Elephant, Hippopotamus)
    - N might be too small to ensure all plant eaters have predators 
    
    seed_nodes: list of nodes from which to randomly choose seed_size starting
    nodes
    """
    
    if seed_nodes is None:
        seed_nodes = G.nodes()
    nodes = set(random.sample(seed_nodes, seed_size))
    
    plant_eaters = get_plant_eaters(G)
    
    for i in range(N - seed_size):
        
        # Identify any plant eaters without predators
        lonely_plant_eaters = {}  # key: plant eater node; value: list of predator nodes
        # For each plant eater in the current subgraph
        for node in plant_eaters & nodes:
            predators = G.successors(node)
            if node in predators:
                predators.remove(node)  # don't count self as predator (cannibals)
            if len(predators) == 0:
                pass
                #print("Lonely plant eater {} has no predators in full graph".format(node))
            # If the current subgraph does not contain any of the plant eater's successors
            elif len(nodes & set(predators)) == 0:
                lonely_plant_eaters[node] = predators
        
        # If there are any lonely plant eaters, add a random predator of of any of them
        # and skip to the next iteration of the loop.
        if len(lonely_plant_eaters) > 0:
            candidate_predators = []
            for node, predators in lonely_plant_eaters.items():
                candidate_predators.extend(predators)
            if len(candidate_predators) > 0:
                nodes.add(random.choice(candidate_predators))
                continue
        
        # Find the neighbor nodes of the subgraph nodes
        neighbors = set()
        for node in nodes:
            neighbors = neighbors | set(G.successors(node))
        neighbors = neighbors - nodes # Exclude nodes already in the subgraph
        
        if len(neighbors) == 0:
            print("predator_complete_subweb: no candidate neighbors found. ", end='')
            if (retry > 0):
                print("Retrying.")
                return predator_complete_subweb(G, N, seed_nodes, seed_size=seed_size,
                                                 retry=retry-1)
            else:
                print("Giving up.")
                return None

        # Add a random neighbor to the subgraph
        nodes.add(random.choice(list(neighbors)))
    
    subgraph = G.subgraph(list(nodes))
    num_components = nx.number_connected_components(subgraph.to_undirected())
    if num_components > 1:
        print("random_successor_subgraph: {} connected components. ".format(num_components),
              end='')
        if (retry > 0):
            print("Retrying.")
            return predator_complete_subweb(G, N, seed_nodes, seed_size=seed_size,
                                             retry=retry-1)
        else:
            print("Giving up.")
            return None
    
    return subgraph

def serengeti_predator_complete_subweb(size, num_basal_species, retry=10):

    serengeti = read_serengeti()

    # For the seed nodes, use the basal species excluding Decaying Material (89)
    seed_nodes = get_basal_species(serengeti)
    if 89 in seed_nodes:
        seed_nodes.remove(89)

    return predator_complete_subweb(serengeti, size, seed_nodes=seed_nodes,
            seed_size=num_basal_species, retry=retry)

if __name__ == '__main__':
    subweb = serengeti_predator_complete_subweb(10, 2)
    species_ids = sorted(subweb.nodes())
    print(species_ids)