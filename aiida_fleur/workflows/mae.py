# -*- coding: utf-8 -*-
###############################################################################
# Copyright (c), Forschungszentrum Jülich GmbH, IAS-1/PGI-1, Germany.         #
#                All rights reserved.                                         #
# This file is part of the AiiDA-FLEUR package.                               #
#                                                                             #
# The code is hosted on GitHub at https://github.com/broeder-j/aiida-fleur    #
# For further information on the license, see the LICENSE.txt file            #
# For further information please visit http://www.flapw.de or                 #
# http://aiida-fleur.readthedocs.io/en/develop/                               #
###############################################################################

"""
    In this module you find the workflow 'fleur_mae_wc' for the calculation of
    Magnetic Anisotropy Energy.
    This workflow consists of modifyed parts of scf and eos workflows.
"""

from aiida.work.workchain import WorkChain, ToContext, if_
from aiida.work.launch import submit
from aiida.orm.data.base import Float
from aiida.work.workfunctions import workfunction as wf
from aiida_fleur.tools.common_fleur_wf import test_and_get_codenode
from aiida_fleur.tools.common_fleur_wf import get_inputs_fleur
from aiida_fleur.workflows.scf import fleur_scf_wc
from aiida.orm import Code, DataFactory, load_node
from aiida_fleur.data.fleurinpmodifier import FleurinpModifier
from aiida.common.datastructures import calc_states

StructureData = DataFactory('structure')
RemoteData = DataFactory('remote')
ParameterData = DataFactory('parameter')
FleurInpData = DataFactory('fleur.fleurinp')

class fleur_mae_wc(WorkChain):
    """
        This workflow calculates the Magnetic Anisotropy Energy of a thin structure.
    """
    
    _workflowversion = "0.1.0a"

    _default_options = {
                        'resources' : {"num_machines": 1, "num_mpiprocs_per_machine" : 1},
                        'max_wallclock_seconds' : 2*60*60,
                        'queue_name' : '',
                        'custom_scheduler_commands' : '',
                        'import_sys_environment' : False,
                        'environment_variables' : {}}
    
    _wf_default = {
                   #'sqa_ref' : ????,                  # Spin Quantization Axis acting as a reference for force theorem calculations
                   'force_th' : True,               #Use the force theorem (True) or converge
                   'fleur_runmax': 10,              # Maximum number of fleur jobs/starts (defauld 30 iterations per start)
                   'density_criterion' : 0.00005,  # Stop if charge denisty is converged below this value
                   'serial' : False,                # execute fleur with mpi or without
                   'itmax_per_run' : 30,
    #do not allow an user to change inp-file manually
                   'inpxml_changes' : [],      # (expert) List of further changes applied after the inpgen run
                   }                                 # tuples (function_name, [parameters]), the ones from fleurinpmodifier
                                                    # example: ('set_nkpts' , {'nkpts': 500,'gamma': False}) ! no checks made, there know what you are doing
    #Specify the list of scf wf paramters to be trasfered into scf wf
    _scf_keys = ['fleur_runmax', 'density_criterion', 'serial', 'itmax_per_run', 'inpxml_changes']

    ERROR_INVALID_INPUT_RESOURCES = 1
    ERROR_INVALID_INPUT_RESOURCES_UNDERSPECIFIED = 2
    ERROR_INVALID_CODE_PROVIDED = 3
    ERROR_INPGEN_CALCULATION_FAILED = 4
    ERROR_CHANGING_FLEURINPUT_FAILED = 5
    ERROR_CALCULATION_INVALID_INPUT_FILE = 6
    ERROR_FLEUR_CALCULATION_FALIED = 7
    ERROR_CONVERGENCE_NOT_ARCHIVED = 8
    ERROR_REFERENCE_CALCULATION_FAILED = 9

    @classmethod
    def define(cls, spec):
        super(fleur_mae_wc, cls).define(spec)
        spec.input("wf_parameters", valid_type=ParameterData, required=False, default=ParameterData(dict=cls._wf_default))
        spec.input("structure", valid_type=StructureData, required=True)
        spec.input("calc_parameters", valid_type=ParameterData, required=False)
        spec.input("inpgen", valid_type=Code, required=True)
        spec.input("fleur", valid_type=Code, required=True)
        spec.input("options", valid_type=ParameterData, required=False, default=ParameterData(dict=cls._default_options))
        spec.input("settings", valid_type=ParameterData, required=False)
                                                                              
        spec.outline(
            cls.start,
            if_(cls.validate_input)(
                cls.converge_scf,
                cls.mae_force,
                cls.get_res_force,
            ).else_(
                cls.converge_scf,
                cls.get_results_converge,
            ),
        )

        spec.output('out', valid_type=ParameterData)

    def start(self):
        """
        Retrieve and initialize paramters of the WorkChain
        """
        self.report('INFO: started Magnetic Anisotropy Energy calculation workflow version {}\n'
                    ''.format(self._workflowversion))
                    
        self.ctx.successful = True
        self.ctx.info = []
        self.ctx.warnings = []
        self.ctx.errors = []

        #Retrieve WorkFlow parameters,
        #initialize the dictionary using defaults if no wf paramters are given by user
        wf_default = self._wf_default
        
        if 'wf_parameters' in self.inputs:
            wf_dict = self.inputs.wf_parameters.get_dict()
        else:
            wf_dict = wf_default
        
        #extend wf parameters given by user using defaults
        for key, val in wf_default.iteritems():
            wf_dict[key] = wf_dict.get(key, val)
        self.ctx.wf_dict = wf_dict
        
        #Retrieve calculation options,
        #initialize the dictionary using defaults if no options are given by user
        defaultoptions = self._default_options
        
        if 'options' in self.inputs:
            options = self.inputs.options.get_dict()
        else:
            options = defaultoptions
        
        #extend options given by user using defaults
        for key, val in defaultoptions.iteritems():
            options[key] = options.get(key, val)
        self.ctx.options = options

        #Check if user gave valid inpgen and fleur execulatbles
        inputs = self.inputs
        if 'inpgen' in inputs:
            try:
                test_and_get_codenode(inputs.inpgen, 'fleur.inpgen', use_exceptions=True)
            except ValueError:
                error = ("The code you provided for inpgen of FLEUR does not "
                         "use the plugin fleur.inpgen")
                self.control_end_wc(error)
                return self.ERROR_INVALID_CODE_PROVIDED

        if 'fleur' in inputs:
            try:
                test_and_get_codenode(inputs.fleur, 'fleur.fleur', use_exceptions=True)
            except ValueError:
                error = ("The code you provided for FLEUR does not "
                         "use the plugin fleur.fleur")
                self.control_end_wc(error)
                return self.ERROR_INVALID_CODE_PROVIDED

    def validate_input(self):
        """
        Choose the branch of MAE calculation:
            a) converge charge density for three orthogonal SQAs (x, y and z directions)
            b) 1) converge charge density for SQA that brakes the symmetry (theta=0.1, phi=0.1)
               2) use the force theorem to find energies for SQAs along x, y and z directions
        SQA = x: theta = pi/2, phi = 0
        SQA = y: theta = pi/2, phi = pi/2
        SQA = z: theta = 0,    phi = 0
        """
        if self.ctx.wf_dict['force_th']:
            self.ctx.inpgen_soc = {'xyz' : ['0.1', '0.1']}
        else:
            self.ctx.inpgen_soc = {'z' : ['0.0', '0.0'], 'x' : ['1.57079', '0.0'], 'y' : ['1.57079', '1.57079']}
        return self.ctx.wf_dict['force_th']

    def converge_scf(self):
        """
        Converge charge density with SOC.
        Depending on a branch of MAE calculation, submit a single Fleur calculation to obtain
        a reference for further force theorem calculations or
        submit thee Fleur calculations to converge charge density for SQA = x, y and z directions.
        """
        inputs = {}
        for key, socs in self.ctx.inpgen_soc.iteritems():
            inputs[key] = self.get_inputs_scf()
            inputs[key]['calc_parameters']['soc'] = {'theta' : socs[0], 'phi' : socs[1]}
            #if key == 'xyz':
            #    inputs[key]['wf_parameters']['inpxml_changes'].append((u'set_inpchanges', {u'change_dict' : {u'alpha' : 0.015}}))
            #else:
            #TODO in case of converge calculation in appends 3 times
            #    inputs[key]['wf_parameters']['inpxml_changes'].append((u'set_inpchanges', {u'change_dict' : {u'alpha' : 0.015}}))
            inputs[key]['wf_parameters'] = ParameterData(dict=inputs[key]['wf_parameters'])
            inputs[key]['calc_parameters'] = ParameterData(dict=inputs[key]['calc_parameters'])
            inputs[key]['options'] = ParameterData(dict=inputs[key]['options'])
            res = self.submit(fleur_scf_wc, **inputs[key])
            self.to_context(**{key:res})
    
    def get_inputs_scf(self):
        """
        Initialize inputs for scf workflow:
        wf_param, options, calculation parameters, codes, structure
        """
        inputs = {}

        # Retrieve scf wf parameters and options form inputs
        #Note that MAE wf parameters contain more information than needed for scf
        #Note: by the time this function is executed, wf_dict is initialized by inputs or defaults
        scf_wf_param = {}
        for key in self._scf_keys:
            scf_wf_param[key] = self.ctx.wf_dict.get(key)
        inputs['wf_parameters'] = scf_wf_param
        
        inputs['options'] = self.ctx.options
        
        #Try to retrieve calculaion parameters from inputs
        try:
            calc_para = self.inputs.calc_parameters.get_dict()
        except AttributeError:
            calc_para = {}
        inputs['calc_parameters'] = calc_para

        #Initialize codes
        inputs['inpgen'] = self.inputs.inpgen
        inputs['fleur'] = self.inputs.fleur
        #Initialize the strucutre
        inputs['structure'] = self.inputs.structure

        return inputs

    def change_fleurinp(self, SQA_direction):
        """
        This routine sets somethings in the fleurinp file before running a fleur
        calculation.
        """
        self.report('INFO: run change_fleurinp')
        try:
            fleurin = self.ctx['xyz'].out.fleurinp
        except AttributeError:
            error = 'A force theorem calculation did not find fleur input generated be the reference claculation.'
            self.control_end_wc(error)
            return self.ERROR_REFERENCE_CALCULATION_FAILED

        #Change SQA from the reference to x, y or z direction.
        #Set itmax = 1
        if SQA_direction == 'x':
            fchanges = [(u'set_inpchanges', {u'change_dict' : {u'theta' : 1.57079, u'phi' : 0.0, u'itmax' : 1}})]
        elif SQA_direction == 'y':
            fchanges = [(u'set_inpchanges', {u'change_dict' : {u'theta' : 1.57079, u'phi' : 1.57079, u'itmax' : 1}})]
        elif SQA_direction == 'z':
            fchanges = [(u'set_inpchanges', {u'change_dict' : {u'theta' : 0.0, u'phi' : 0.0, u'itmax' : 1}})]

        #This part of code was copied from scf workflow. If it contains bugs,
        #they also has to be fixed in scf wf
        if fchanges:# change inp.xml file
            fleurmode = FleurinpModifier(fleurin)
            avail_ac_dict = fleurmode.get_avail_actions()

            # apply further user dependend changes
            for change in fchanges:
                function = change[0]
                para = change[1]
                method = avail_ac_dict.get(function, None)
                if not method:
                    error = ("ERROR: Input 'inpxml_changes', function {} "
                                "is not known to fleurinpmodifier class, "
                                "plaese check/test your input. I abort..."
                                "".format(method))
                    self.control_end_wc(error)
                    return self.ERROR_CHANGING_FLEURINPUT_FAILED

                else:# apply change
                    method(**para)

            # validate?
            apply_c = True
            try:
                fleurmode.show(display=False, validate=True)
            except XMLSyntaxError:
                error = ('ERROR: input, user wanted inp.xml changes did not validate')
                #fleurmode.show(display=True)#, validate=True)
                self.report(error)
                apply_c = False
                return self.ERROR_CALCULATION_INVALID_INPUT_FILE
            
            # apply
            if apply_c:
                out = fleurmode.freeze()
                self.ctx.fleurinp = out
            return
        else: # otherwise do not change the inp.xml
            self.ctx.fleurinp = fleurin
            return

    def mae_force(self):
        """
        Calculate energy of a system with given SQA
        using the force theorem. Converged reference stores in self.ctx['xyz'].
        """
        self.report('INFO: run Force theorem calculations')

        for SQA_direction in ['x', 'y', 'z']:
            self.change_fleurinp(SQA_direction)
            fleurin = self.ctx.fleurinp

            #Do not copy broyd* files from the parent
            settings = ParameterData(dict={'remove_from_remotecopy_list': ['broyd*']})
        
            #Retrieve remote folder of the reference calculation
            scf_ref_node = load_node(self.ctx['xyz'].pk)
            for i in scf_ref_node.called:
                if i.type == u'calculation.job.fleur.fleur.FleurCalculation.':
                    remote_old = i.out.remote_folder
            
            label = 'Force_{}'.format(SQA_direction)
            description = 'This is a force theorem calculation for {} SQA'.format(SQA_direction)

            code = self.inputs.fleur
            options = self.ctx.options.copy()

            inputs_builder = get_inputs_fleur(code, remote_old, fleurin, options, label, description, settings, serial=False)
            future = submit(inputs_builder)
            key = 'force_{}'.format(SQA_direction)
            self.to_context(**{key:future})

    def get_res_force(self):
        
        htr2eV = 27.21138602
        t_energydict = {}
        t_energydict['MAE_x'] = self.ctx['force_x'].out.output_parameters.dict.energy
        t_energydict['MAE_y'] = self.ctx['force_y'].out.output_parameters.dict.energy
        t_energydict['MAE_z'] = self.ctx['force_z'].out.output_parameters.dict.energy
        e_u = self.ctx['force_x'].out.output_parameters.dict.energy_units
        
        #Find a minimal value of MAE and count it as 0
        labelmin = 'MAE_z'
        for labels in ['MAE_y', 'MAE_x']:
            if t_energydict[labels] < t_energydict[labels]:
                labelmin = labels
        minenergy = t_energydict[labelmin]

        for key, val in t_energydict.iteritems():
            t_energydict[key] = t_energydict[key] - minenergy
            if e_u == 'Htr' or 'htr':
                t_energydict[key] = t_energydict[key] * htr2eV
        
        out = {'workflow_name' : self.__class__.__name__,
               'workflow_version' : self._workflowversion,
               'initial_structure': self.inputs.structure.uuid,
               'MAE_x' : t_energydict['MAE_x'],
               'MAE_y' : t_energydict['MAE_y'],
               'MAE_z' : t_energydict['MAE_z'],
               'MAE_units' : e_u,
               'successful' : self.ctx.successful,
               'info' : self.ctx.info,
               'warnings' : self.ctx.warnings,
               'errors' : self.ctx.errors}
        
        self.out('out', ParameterData(dict=out))

    def get_results_converge(self):
        """
        Retrieve results of converge calculations
        """
        distancedict ={}
        t_energydict = {}
        outnodedict = {}
        htr2eV = 27.21138602
        
        for label in ['x', 'y', 'z']:
            calc = self.ctx[label]
            try:
                outnodedict[label] = calc.get_outputs_dict()['output_scf_wc_para']
            except KeyError:
                message = ('One SCF workflow failed, no scf output node: {}. I skip this one.'.format(label))
                self.ctx.errors.append(message)
                self.ctx.successful = False
                continue
            
            outpara = calc.get_outputs_dict()['output_scf_wc_para'].get_dict()
            
            if not outpara.get('successful', False):
                #TODO: maybe do something else here
                # (exclude point and write a warning or so, or error treatment)
                # bzw implement and scf_handler,
                #TODO also if not perfect converged, results might be good
                message = ('One SCF workflow was not successful: {}'.format(label))
                self.ctx.warning.append(message)
                self.ctx.successful = False
            
            t_e = outpara.get('total_energy', float('nan'))
            e_u = outpara.get('total_energy_units', 'eV')
            if e_u == 'Htr' or 'htr':
                t_e = t_e * htr2eV
            t_energydict[label] = t_e
        
        #Find a minimal value of MAE and count it as 0
        labelmin = 'z'
        for labels in ['y', 'x']:
            try:
                if t_energydict[labels] < t_energydict[labels]:
                    labelmin = labels
            except KeyError:
                pass
        minenergy = t_energydict[labelmin]

        for key, val in t_energydict.iteritems():
            t_energydict[key] = t_energydict[key] - minenergy
        
        out = {'workflow_name' : self.__class__.__name__,
               'workflow_version' : self._workflowversion,
               'initial_structure': self.inputs.structure.uuid,
               'MAE_x' : t_energydict['x'],
               'MAE_y' : t_energydict['y'],
               'MAE_z' : t_energydict['z'],
               'MAE_units' : e_u,
               'successful' : self.ctx.successful,
               'info' : self.ctx.info,
               'warnings' : self.ctx.warnings,
               'errors' : self.ctx.errors}
   
        if self.ctx.successful:
            self.report('Done, Magnetic Anisotropy Energy calculation using convergence complete')
        else:
            self.report('Done, but something went wrong.... Properly some individual calculation failed or a scf-cylcle did not reach the desired distance.')

        # create link to workchain node
        self.out('out', ParameterData(dict=out))

    def control_end_wc(self, errormsg):
        """
        Controled way to shutdown the workchain. will initalize the output nodes
        The shutdown of the workchain will has to be done afterwards
        """
        self.ctx.successful = False
        self.ctx.abort = True
        self.report(errormsg) # because return_results still fails somewhen
        self.ctx.errors.append(errormsg)
        self.return_results()
        
        return

'''
@wf
def create_mae_result_node(**kwargs):
    """
    This is a pseudo wf, to create the rigth graph structure of AiiDA.
    This wokfunction will create the output node in the database.
    It also connects the output_node to all nodes the information commes from.
    So far it is just also parsed in as argument, because so far we are to lazy
    to put most of the code overworked from return_results in here.
    """
    outdict = {}
    outpara = kwargs.get('results_node', {})
    outdict['output_eos_wc_para'] = outpara.clone()
    # copy, because we rather produce the same node twice
    # then have a circle in the database for now...
    outputdict = outpara.get_dict()
    structure = load_node(outputdict.get('initial_structure'))
    #gs_scaling = outputdict.get('scaling_gs', 0)
    #if gs_scaling:
    #    gs_structure = rescale(structure, Float(gs_scaling))
    #    outdict['gs_structure'] = gs_structure

    return outdict
'''
