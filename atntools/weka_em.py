"""
Functions for dealing with Weka's EM output
"""

import re

def parse_weka_em_output(priors, text):
    """
    Parse the portion of the output from Weka's EM clusterer that gives the
    distribution parameters for each attribute.  Doesn't parse cluster priors;
    they must be supplied as an argument.  The return value is a list of
    dictionaries - one for each cluster - structured like the following example:
    
[
    {
        "prior": 0.35,
        "nodes": {
            "5": {
                "K": {
                    "mean": 8025.473,
                    "stdDev": 2253.5472
                },
                "initialBiomass": {
                    "mean": 2085.6366,
                    "stdDev": 506.5151
                }
            },
            "14": {
                "X": {
                    "mean": 0.2048,
                    "stdDev": 0.0588
                },
                "initialBiomass": {
                    "mean": 669.0392,
                    "stdDev": 91.3827
                }
            }
        }
    },
    
    {
        "prior": 0.65,
        "nodes": {
            "5": {
                "K": {
                    "mean": 8326.2055,
                    "stdDev": 2189.6134
                },
                "initialBiomass": {
                    "mean": 2023.5001,
                    "stdDev": 578.9036
                }
            },
            "14": {
                "X": {
                    "mean": 0.2043,
                    "stdDev": 0.0585
                },
                "initialBiomass": {
                    "mean": 1185.7895,
                    "stdDev": 231.4305
                }
            }
        }
    }
]
    """
    
    dist = [{'prior': p, 'nodes': {}} for p in priors]
    
    for line in text.split('\n'):
        if len(line.strip()) == 0:
            # skip blank line
            continue
        first_digit_pos = re.search(r'\d', line).start()
        if line[0] != ' ':
            # Found a line giving the attribute name
            param_name = line[:first_digit_pos]
            node_id = int(line[first_digit_pos:])
        else:
            # Found a line giving means or standard deviations for an attribute
            if line.lstrip().startswith('mean'):
                dist_param_name = 'mean'
            if line.lstrip().startswith('std. dev.'):
                dist_param_name = 'stdDev'
            for k, dist_param_value in enumerate(
                    [float(x) for x in line[first_digit_pos:].split()]):
                if node_id not in dist[k]['nodes']:
                    dist[k]['nodes'][node_id] = {}
                if param_name not in dist[k]['nodes'][node_id]:
                    dist[k]['nodes'][node_id][param_name] = {}
                dist[k]['nodes'][node_id][param_name][dist_param_name] = dist_param_value
    
    return dist

def parse_weka_em_output_file(filename):
    """
    Given a full Weka EM output filename, return parsed cluster information as
    returned by parse_weka_em_output().
    """
    f = open(filename)
    priors = None
    param_output_lines = []
    for line in f:
        if line.lstrip().startswith('('):
            # We've found the line with the priors
            priors = [float(s) for s in
                    line.replace('(', '').replace(')', '').split()]
            f.__next__()
            continue
        elif priors is not None:
            if line.startswith('Time taken'):
                break
            param_output_lines.append(line)
    clusters = parse_weka_em_output(priors, ''.join(param_output_lines))
    return clusters

