# -*- coding: utf-8 -*-
###############################################################################
# Copyright (c), Forschungszentrum Jülich GmbH, IAS-1/PGI-1, Germany.         #
#                All rights reserved.                                         #
# This file is part of the AiiDA-FLEUR package.                               #
#                                                                             #
# The code is hosted on GitHub at https://github.com/JuDFTteam/aiida-fleur    #
# For further information on the license, see the LICENSE.txt file            #
# For further information please visit http://www.flapw.de or                 #
# http://aiida-fleur.readthedocs.io/en/develop/                               #
###############################################################################
'''
Module for the command line interface of AiiDA-FLEUR
'''
import click
import click_completion

from aiida.cmdline.params import options, types

# Activate the completion of parameter types provided by the click_completion package
click_completion.init()

# for bash use eval "$(_AIIDA_FLEUR_COMPLETE=source_bash aiida-fleur)"

# Instead of using entrypoints and directly injecting verdi commands into aiida-core
# we created our own separete CLI because verdi will prob change and become
# less material science specific


@click.group('aiida-fleur', context_settings={'help_option_names': ['-h', '--help']})
@options.PROFILE(type=types.ProfileParamType(load_profile=True))
def cmd_root(profile):  # pylint: disable=unused-argument
    """CLI for the `aiida-fleur` plugin."""


from .launch import cmd_launch
from .data import cmd_data
from .workflows import cmd_workflow
from .visualization import cmd_plot
