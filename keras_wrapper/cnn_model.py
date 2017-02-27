import matplotlib as mpl
from keras.engine.training import Model
from keras.layers import Convolution2D, MaxPooling2D, ZeroPadding2D, AveragePooling2D, Deconvolution2D, \
    ArbitraryDeconvolution2D
from keras.layers import merge, Dense, Dropout, Flatten, Input, Activation, BatchNormalization
from keras.layers.advanced_activations import PReLU
from keras.models import Sequential, model_from_json
from keras.optimizers import SGD
from keras.regularizers import l2
from keras.utils import np_utils
from keras.utils.layer_utils import print_summary
from keras import backend as K

from keras_wrapper.dataset import Data_Batch_Generator, Homogeneous_Data_Batch_Generator
from keras_wrapper.deprecated.thread_loader import ThreadDataLoader, retrieveXY
from keras_wrapper.extra.callbacks import *
from keras_wrapper.extra.read_write import file2list

mpl.use('Agg')  # run matplotlib without X server (GUI)
import matplotlib.pyplot as plt

import numpy as np
import cPickle as pk
import cloud.serialization.cloudpickle as cloudpk

import sys
import time
import os
import math
import copy
import shutil

import logging

logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
logger = logging.getLogger(__name__)

from keras.optimizers import Adam, RMSprop, Nadam, Adadelta, SGD, Adagrad, Adamax
from keras.applications.vgg19 import VGG19


# ------------------------------------------------------- #
#       SAVE/LOAD
#           External functions for saving and loading Model_Wrapper instances
# ------------------------------------------------------- #


def saveModel(model_wrapper, update_num, path=None, full_path=False, store_iter=False):
    """
    Saves a backup of the current Model_Wrapper object after being trained for 'update_num' iterations/updates/epochs.

    :param model_wrapper: object to save
    :param update_num: identifier of the number of iterations/updates/epochs elapsed
    :param path: path where the model will be saved
    :param full_path: Whether we save to the path of from path + '/epoch_' + update_num
    :param store_iter: Whether we store the current update_num
    :return: None
    """
    if not path:
        path = model_wrapper.model_path

    iter = str(update_num)

    if full_path:
        if store_iter:
            model_name = path + '_' + iter
        else:
            model_name = path
    else:
        if store_iter:
            model_name = path + '/update_' + iter
        else:
            model_name = path + '/epoch_' + iter

    if not model_wrapper.silence:
        logging.info("<<< Saving model to " + model_name + " ... >>>")

    # Create models dir
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path))

    # Save model structure
    json_string = model_wrapper.model.to_json()
    open(model_name + '_structure.json', 'w').write(json_string)
    # Save model weights
    model_wrapper.model.save_weights(model_name + '_weights.h5', overwrite=True)

    # Save auxiliar models for optimized search
    if model_wrapper.model_init is not None:
        logging.info("<<< Saving model_init to " + model_name + "_structure_init.json... >>>")
        # Save model structure
        json_string = model_wrapper.model_init.to_json()
        open(model_name + '_structure_init.json', 'w').write(json_string)
        # Save model weights
        model_wrapper.model_init.save_weights(model_name + '_weights_init.h5', overwrite=True)
    if model_wrapper.model_next is not None:
        logging.info("<<< Saving model_next to " + model_name + "_structure_next.json... >>>")
        # Save model structure
        json_string = model_wrapper.model_next.to_json()
        open(model_name + '_structure_next.json', 'w').write(json_string)
        # Save model weights
        model_wrapper.model_next.save_weights(model_name + '_weights_next.h5', overwrite=True)

    # Save additional information
    cloudpk.dump(model_wrapper, open(model_name + '_Model_Wrapper.pkl', 'wb'))

    if not model_wrapper.silence:
        logging.info("<<< Model saved >>>")


def loadModel(model_path, update_num, reload_epoch=True, custom_objects=dict(), full_path=False):
    """
    Loads a previously saved Model_Wrapper object.

    :param model_path: path to the Model_Wrapper object to load
    :param update_num: identifier of the number of iterations/updates/epochs elapsed
    :param custom_objects: dictionary of custom layers (i.e. input to model_from_json)
    :return: loaded Model_Wrapper
    """
    t = time.time()
    iter = str(update_num)

    if full_path:
        model_name = model_path
    else:
        if reload_epoch:
            model_name = model_path + "/epoch_" + iter
        else:
            model_name = model_path + "/update_" + iter

    logging.info("<<< Loading model from " + model_name + "_Model_Wrapper.pkl ... >>>")

    # Load model structure
    model = model_from_json(open(model_name + '_structure.json').read(), custom_objects=custom_objects)

    # Load model weights
    model.load_weights(model_name + '_weights.h5')

    # Load auxiliar models for optimized search
    if os.path.exists(model_name + '_structure_init.json') and \
            os.path.exists(model_name + '_weights_init.h5') and \
            os.path.exists(model_name + '_structure_next.json') and \
            os.path.exists(model_name + '_weights_next.h5'):
        loaded_optimized = True
    else:
        loaded_optimized = False

    if loaded_optimized:
        # Load model structure
        logging.info("<<< Loading optimized model... >>>")
        logging.info("\t <<< Loading model_init from " + model_name + "_structure_init.json ... >>>")
        model_init = model_from_json(open(model_name + '_structure_init.json').read(), custom_objects=custom_objects)
        # Load model weights
        model_init.load_weights(model_name + '_weights_init.h5')
        # Load model structure
        logging.info("\t <<< Loading model_next from " + model_name + "_structure_next.json ... >>>")
        model_next = model_from_json(open(model_name + '_structure_next.json').read(), custom_objects=custom_objects)
        # Load model weights
        model_next.load_weights(model_name + '_weights_next.h5')

    # Load Model_Wrapper information
    try:
        model_wrapper = pk.load(open(model_name + '_Model_Wrapper.pkl', 'rb'))
    except:  # backwards compatibility
        #try:
        model_wrapper = pk.load(open(model_name + '_CNN_Model.pkl', 'rb'))
        #except:
        #    raise Exception(ValueError)

    # Add logger for backwards compatibility (old pre-trained models) if it does not exist
    model_wrapper.updateLogger()

    model_wrapper.model = model
    if loaded_optimized:
        model_wrapper.model_init = model_init
        model_wrapper.model_next = model_next
        logging.info("<<< Optimized model loaded. >>>")
    else:
        model_wrapper.model_init = None
        model_wrapper.model_next = None
    logging.info("<<< Model loaded in %0.6s seconds. >>>" % str(time.time() - t))
    return model_wrapper


def updateModel(model, model_path, update_num, reload_epoch=True, full_path=False):
    """
    Loads a the weights from files to a Model_Wrapper object.

    :param model: Model_Wrapper object to update
    :param model_path: path to the weights to load
    :param update_num: identifier of the number of iterations/updates/epochs elapsed
    :return: updated Model_Wrapper
    """
    t = time.time()
    model_name = model.name
    iter = str(update_num)

    if not full_path:
        if reload_epoch:
            model_path = model_path + "/epoch_" + iter
        else:
            model_path = model_path + "/update_" + iter

    logging.info("<<< Updating model " + model_name + " from " + model_path + " ... >>>")

    # Load model weights
    model.model.load_weights(model_path + '_weights.h5')

    # Load auxiliar models for optimized search
    if os.path.exists(model_path + '_weights_init.h5') and os.path.exists(model_path + '_weights_next.h5'):
        loaded_optimized = True
    else:
        loaded_optimized = False

    if loaded_optimized:
        # Load model structure
        logging.info("<<< Updating optimized model... >>>")
        logging.info("\t <<< Updating model_init from " + model_path + "_structure_init.json ... >>>")
        model.model_init.load_weights(model_path + '_weights_init.h5')
        # Load model structure
        logging.info("\t <<< Updating model_next from " + model_path + "_structure_next.json ... >>>")
        # Load model weights
        model.model_next.load_weights(model_path + '_weights_next.h5')

    logging.info("<<< Model updated in %0.6s seconds. >>>" % str(time.time() - t))
    return model


def transferWeights(old_model, new_model, layers_mapping):
    """
    Transfers all existent layer' weights from an old model to a new model.

    :param old_model: old version of the model, where the weights will be picked
    :param new_model: new version of the model, where the weights will be transfered to
    :param layers_mapping: mapping from old to new model layers
    :return: new model with weights transfered
    """

    logging.info("<<< Transferring weights from models. >>>")

    old_layer_dict = dict([(layer.name, [layer, idx]) for idx, layer in enumerate(old_model.model.layers)])
    new_layer_dict = dict([(layer.name, [layer, idx]) for idx, layer in enumerate(new_model.model.layers)])

    for lold, lnew in layers_mapping.iteritems():
        # Check if layers exist in both models
        if lold in old_layer_dict and lnew in new_layer_dict:

            # Create dictionary name --> layer
            old = old_layer_dict[lold][0].get_weights()
            new = new_layer_dict[lnew][0].get_weights()

            # Find weight sizes matchings for each layer (without repetitions)
            new_shapes = [w.shape for w in new]
            mapping_weights = dict()
            for pos_old, wo in enumerate(old):
                old_shape = wo.shape
                indices = [i for i, shp in enumerate(new_shapes) if shp == old_shape]
                if indices:
                    for ind in indices:
                        if ind not in mapping_weights.keys():
                            mapping_weights[ind] = pos_old
                            break

            # Alert for any weight matrix not inserted to new model
            for pos_old, wo in enumerate(old):
                if pos_old not in mapping_weights.values():
                    logging.info('  Pre-trained weight matrix of layer "' + lold +
                                 '" with dimensions '+str(wo.shape)+' can not be inserted to new model.')

            # Alert for any weight matrix not modified
            for pos_new, wn in enumerate(new):
                if pos_new not in mapping_weights.keys():
                    logging.info('  New model weight matrix of layer "' + lnew +
                                 '" with dimensions ' + str(wn.shape) + ' can not be loaded from pre-trained model.')

            # Transfer weights for each layer
            for new_idx, old_idx in mapping_weights.iteritems():
                new[new_idx] = old[old_idx]
            new_model.model.layers[new_layer_dict[lnew][1]].set_weights(new)

        else:
            logging.info('Can not apply weights transfer from "'+lold+'" to "'+lnew+'"')

    logging.info("<<< Weights transferred successfully. >>>")

    return new_model


# ------------------------------------------------------- #
#       MAIN CLASS
# ------------------------------------------------------- #
class Model_Wrapper(object):
    """
        Wrapper for Keras' models. It provides the following utilities:
            - Training visualization module.
            - Set of already implemented CNNs for quick definition.
            - Easy layers re-definition for finetuning.
            - Model backups.
            - Easy to use training and test methods.
    """

    def __init__(self, nOutput=1000, type='basic_model', silence=False, input_shape=[256, 256, 3],
                 structure_path=None, weights_path=None, seq_to_functional=False,
                 model_name=None, plots_path=None, models_path=None, inheritance=False):
        """
            Model_Wrapper object constructor.

            :param nOutput: number of outputs of the network. Only valid if 'structure_path' == None.
            :param type: network name type (corresponds to any method defined in the section 'MODELS' of this class). Only valid if 'structure_path' == None.
            :param silence: set to True if you don't want the model to output informative messages
            :param input_shape: array with 3 integers which define the images' input shape [height, width, channels]. Only valid if 'structure_path' == None.
            :param structure_path: path to a Keras' model json file. If we speficy this parameter then 'type' will be only an informative parameter.
            :param weights_path: path to the pre-trained weights file (if None, then it will be randomly initialized)
            :param seq_to_functional: indicates if we are loading a set of weights trained on a Sequential model to a Functional one
            :param model_name: optional name given to the network (if None, then it will be assigned to current time as its name)
            :param plots_path: path to the folder where the plots will be stored during training
            :param models_path: path to the folder where the temporal model packups will be stored
            :param inheritance: indicates if we are building an instance from a child class (in this case the model will not be built from this __init__, it should be built from the child class).
        """
        self.__toprint = ['net_type', 'name', 'plot_path', 'models_path', 'lr', 'momentum',
                          'training_parameters', 'testing_parameters', 'training_state', 'loss', 'silence']

        self.silence = silence
        self.net_type = type
        self.lr = 0.01  # insert default learning rate
        self.momentum = 1.0 - self.lr  # insert default momentum
        self.loss = 'categorical_crossentropy'  # default loss function
        self.training_parameters = []
        self.testing_parameters = []
        self.training_state = dict()

        # Dictionary for storing any additional data needed
        self.additional_data = dict()

        # Model containers
        self.model = None
        self.model_init = None
        self.model_next = None

        # Inputs and outputs names for models of class Model
        self.ids_inputs = list()
        self.ids_outputs = list()

        # Inputs and outputs names for models for optimized search
        self.ids_inputs_init = list()
        self.ids_outputs_init = list()
        self.ids_inputs_next = list()
        self.ids_outputs_next = list()

        # Matchings from model_init to mode_next:
        self.matchings_init_to_next = None
        self.matchings_next_to_next = None

        # Inputs and outputs names for models with temporally linked samples
        self.ids_temporally_linked_inputs = list()

        # Matchings between temporally linked samples
        self.matchings_sample_to_next_sample = None

        # Prepare logger
        self.updateLogger()

        # Prepare model
        if not inheritance:
            # Set Network name
            self.setName(model_name, plots_path, models_path)

            if structure_path:
                # Load a .json model
                if not self.silence:
                    logging.info("<<< Loading model structure from file " + structure_path + " >>>")
                self.model = model_from_json(open(structure_path).read())

            else:
                # Build model from scratch
                if hasattr(self, type):
                    if not self.silence:
                        logging.info("<<< Building " + type + " Model_Wrapper >>>")
                    eval('self.' + type + '(nOutput, input_shape)')
                else:
                    raise Exception('Model_Wrapper type "' + type + '" is not implemented.')

            # Load weights from file
            if weights_path:
                if not self.silence:
                    logging.info("<<< Loading weights from file " + weights_path + " >>>")
                self.model.load_weights(weights_path, seq_to_functional=seq_to_functional)

    def updateLogger(self):
        """
            Checks if the model contains an updated logger.
            If it doesn't then it updates it, which will store evaluation results.
        """
        compulsory_data_types = ['iteration', 'loss', 'accuracy', 'accuracy top-5']
        if '_Model_Wrapper__logger' not in self.__dict__:
            self.__logger = dict()
        if '_Model_Wrapper__data_types' not in self.__dict__:
            self.__data_types = compulsory_data_types
        else:
            for d in compulsory_data_types:
                if d not in self.__data_types:
                    self.__data_types.append(d)

        self.__modes = ['train', 'val', 'test']

    def setInputsMapping(self, inputsMapping):
        """
            Sets the mapping of the inputs from the format given by the dataset to the format received by the model.

            :param inputsMapping: dictionary with the model inputs' identifiers as keys and the dataset inputs identifiers' position as values. If the current model is Sequential then keys must be ints with the desired input order (starting from 0). If it is Model then keys must be str.
        """
        self.inputsMapping = inputsMapping

    def setOutputsMapping(self, outputsMapping, acc_output=None):
        """
            Sets the mapping of the outputs from the format given by the dataset to the format received by the model.

            :param outputsMapping: dictionary with the model outputs' identifiers as keys and the dataset outputs identifiers' position as values. If the current model is Sequential then keys must be ints with the desired output order (in this case only one value can be provided). If it is Model then keys must be str.
            :param acc_output: name of the model's output that will be used for calculating the accuracy of the model (only needed for Graph models)
        """
        if isinstance(self.model, Sequential) and len(outputsMapping.keys()) > 1:
            raise Exception("When using Sequential models only one output can be provided in outputsMapping")
        self.outputsMapping = outputsMapping
        self.acc_output = acc_output

    def setOptimizer(self, lr=None, momentum=None, loss=None, metrics=None,
                     decay=0.0, clipnorm=10., clipvalue=0., optimizer=None, sample_weight_mode=None):
        """
            Sets a new optimizer for the CNN model.

            :param lr: learning rate of the network
            :param momentum: momentum of the network (if None, then momentum = 1-lr)
            :param loss: loss function applied for optimization
            :param metrics: list of Keras' metrics used for evaluating the model. To specify different metrics for different outputs of a multi-output model, you could also pass a dictionary, such as `metrics={'output_a': 'accuracy'}`.
            :param decay: lr decay
            :param clipnorm: gradients' clip norm
            :param optimizer: string identifying the type of optimizer used (default: SGD)
            :param sample_weight_mode: 'temporal' or None
        """
        # Pick default parameters
        if lr is None:
            lr = self.lr
        else:
            self.lr = lr
        if momentum is None:
            momentum = self.momentum
        else:
            self.momentum = momentum
        if loss is None:
            loss = self.loss
        else:
            self.loss = loss
        if metrics is None:
            metrics = []

        if optimizer is None or optimizer.lower() == 'sgd':
            optimizer = SGD(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay, momentum=momentum, nesterov=True)
        elif optimizer.lower() == 'adam':
            optimizer = Adam(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        elif optimizer.lower() == 'adagrad':
            optimizer = Adagrad(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        elif optimizer.lower() == 'rmsprop':
            optimizer = RMSprop(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        elif optimizer.lower() == 'nadam':
            optimizer = Nadam(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        elif optimizer.lower() == 'adamax':
            optimizer = Adamax(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        elif optimizer.lower() == 'adadelta':
            optimizer = Adadelta(lr=lr, clipnorm=clipnorm, clipvalue=clipvalue, decay=decay)
        else:
            raise Exception('\tThe chosen optimizer is not implemented.')

        if not self.silence:
            logging.info("Compiling model...")

        # compile differently depending if our model is 'Sequential', 'Model' or 'Graph'
        if isinstance(self.model, Sequential) or isinstance(self.model, Model):
            self.model.compile(optimizer=optimizer, metrics=metrics, loss=loss,
                               sample_weight_mode=sample_weight_mode)
        else:
            raise NotImplementedError()

        if not self.silence:
            logging.info("Optimizer updated, learning rate set to " + str(lr))

    def setName(self, model_name, plots_path=None, models_path=None, create_plots=False, clear_dirs=True):
        """
                    Changes the name (identifier) of the Model_Wrapper instance.
        :param model_name:  New model name
        :param plots_path: Path where to store the plots
        :param models_path: Path where to store the model
        :param create_plots: Whether we'll store plots or not
        :param clear_dirs: Whether the store_path directory will be erased or not
        :return: None
        """
        if not model_name:
            self.name = time.strftime("%Y-%m-%d") + '_' + time.strftime("%X")
            create_dirs = False
        else:
            self.name = model_name
            create_dirs = True

        if create_plots:
            if not plots_path:
                self.plot_path = 'Plots/' + self.name
            else:
                self.plot_path = plots_path

        if not models_path:
            self.model_path = 'Models/' + self.name
        else:
            self.model_path = models_path

        # Remove directories if existed
        if clear_dirs:
            if os.path.isdir(self.model_path):
                shutil.rmtree(self.model_path)
            if create_plots:
                if os.path.isdir(self.plot_path):
                    shutil.rmtree(self.plot_path)

        # Create new ones
        if create_dirs:
            if not os.path.isdir(self.model_path):
                os.makedirs(self.model_path)
            if create_plots:
                if not os.path.isdir(self.plot_path):
                    os.makedirs(self.plot_path)


    def setParams(self, params):
        self.params = params


    def checkParameters(self, input_params, default_params):
        """
            Validates a set of input parameters and uses the default ones if not specified.
        """
        valid_params = [key for key in default_params]
        params = dict()

        # Check input parameters' validity
        for key, val in input_params.iteritems():
            if key in valid_params:
                params[key] = val
            else:
                raise Exception("Parameter '" + key + "' is not a valid parameter.")

        # Use default parameters if not provided
        for key, default_val in default_params.iteritems():
            if key not in params:
                params[key] = default_val

        return params

    # ------------------------------------------------------- #
    #       MODEL MODIFICATION
    #           Methods for modifying specific layers of the network
    # ------------------------------------------------------- #

    def replaceLastLayers(self, num_remove, new_layers):
        """
            Replaces the last 'num_remove' layers in the model by the newly defined in 'new_layers'.
            Function only valid for Sequential models. Use self.removeLayers(...) for Graph models.
        """
        if not self.silence:
            logging.info("Replacing layers...")

        removed_layers = []
        removed_params = []
        # If it is a Sequential model
        if isinstance(self.model, Sequential):
            # Remove old layers
            for i in range(num_remove):
                removed_layers.append(self.model.layers.pop())
                removed_params.append(self.model.params.pop())

            # Insert new layers
            for layer in new_layers:
                self.model.add(layer)

        # If it is a Graph model
        else:
            raise NotImplementedError("Try using self.removeLayers(...) instead.")

        return [removed_layers, removed_params]

    # ------------------------------------------------------- #
    #       TRAINING/TEST
    #           Methods for train and testing on the current Model_Wrapper
    # ------------------------------------------------------- #

    def ended_training(self):
        """
            Indicates if the model has early stopped.
        """
        if hasattr(self.model, 'callback_model') and self.model.callback_model:
            callback_model = self.callback_model
        else:
            callback_model = self

        if hasattr(callback_model, 'stop_training') and callback_model.stop_training == True:
            return True
        else:
            return False

    def trainNet(self, ds, parameters={}, out_name=None):
        """
            Trains the network on the given dataset 'ds'.

            :param out_name: name of the output node that will be used to evaluate the network accuracy. Only applicable to Graph models.

            The input 'parameters' is a dict() which may contain the following (optional) training parameters:

            ####    Visualization parameters

            :param report_iter: number of iterations between each loss report
            :param iter_for_val: number of interations between each validation test
            :param num_iterations_val: number of iterations applied on the validation dataset for computing the average performance (if None then all the validation data will be tested)

            ####    Learning parameters

            :param n_epochs: number of epochs that will be applied during training
            :param batch_size: size of the batch (number of images) applied on each interation by the SGD optimization
            :param lr_decay: number of iterations passed for decreasing the learning rate
            :param lr_gamma: proportion of learning rate kept at each decrease. It can also be a set of rules defined by a list, e.g. lr_gamma = [[3000, 0.9], ..., [None, 0.8]] means 0.9 until iteration 3000, ..., 0.8 until the end.
            :param patience: number of epochs waiting for a possible performance increase before stopping training
            :param metric_check: name of the metric checked for early stoppping and LR decrease

            ####    Data processing parameters

            :param n_parallel_loaders: number of parallel data loaders allowed to work at the same time
            :param normalize: boolean indicating if we want to 0-1 normalize the image pixel values
            :param mean_substraction: boolean indicating if we want to substract the training mean
            :param data_augmentation: boolean indicating if we want to perform data augmentation (always False on validation)
            :param shuffle: apply shuffling on training data at the beginning of each epoch.

            ####    Other parameters

            :param save_model: number of iterations between each model backup
        """

        # Check input parameters and recover default values if needed

        default_params = {'n_epochs': 1, 'batch_size': 50,
                          'maxlen': 100,  # sequence learning parameters (BeamSearch)
                          'homogeneous_batches': False,
                          'joint_batches': 4,
                          'epochs_for_save': 1,
                          'num_iterations_val': None,
                          'n_parallel_loaders': 8,
                          'normalize': False,
                          'mean_substraction': True,
                          'data_augmentation': True,
                          'verbose': 1, 'eval_on_sets': ['val'],
                          'reload_epoch': 0,
                          'extra_callbacks': [],
                          'shuffle': True,
                          'epoch_offset': 0,
                          'patience': 0,
                          'metric_check': None,
                          'eval_on_epochs': True,
                          'each_n_epochs': 1,
                          'start_eval_on_epoch':0, # early stopping parameters
                          'lr_decay': None, # LR decay parameters
                          'lr_gamma': 0.1}
        params = self.checkParameters(parameters, default_params)
        save_params = copy.copy(params)
        del save_params['extra_callbacks']
        self.training_parameters.append(save_params)
        if params['verbose'] > 0:
            logging.info("<<< Training model >>>")

        self.__train(ds, params)

        logging.info("<<< Finished training model >>>")

    def resumeTrainNet(self, ds, parameters, out_name=None):
        """
            DEPRECATED

            Resumes the last training state of a stored model keeping also its training parameters.
            If we introduce any parameter through the argument 'parameters', it will be replaced by the old one.

            :param out_name: name of the output node that will be used to evaluate the network accuracy. Only applicable for Graph models.
        """

        raise NotImplementedError('Deprecated')

        # Recovers the old training parameters (replacing them by the new ones if any)
        default_params = self.training_parameters[-1]
        params = self.checkParameters(parameters, default_params)
        self.training_parameters.append(copy.copy(params))

        # Recovers the last training state
        state = self.training_state

        logging.info("<<< Resuming training model >>>")

        self.__train(ds, params, state)

        logging.info("<<< Finished training Model_Wrapper >>>")

    def trainNetFromSamples(self, x, y, parameters={}, class_weight=None, sample_weight=None, out_name=None):
        """
            Trains the network on the given samples x, y.

            :param out_name: name of the output node that will be used to evaluate the network accuracy. Only applicable to Graph models.

            The input 'parameters' is a dict() which may contain the following (optional) training parameters:

            ####    Visualization parameters

            :param report_iter: number of iterations between each loss report
            :param iter_for_val: number of interations between each validation test
            :param num_iterations_val: number of iterations applied on the validation dataset for computing the average performance (if None then all the validation data will be tested)

            ####    Learning parameters

            :param n_epochs: number of epochs that will be applied during training
            :param batch_size: size of the batch (number of images) applied on each interation by the SGD optimization
            :param lr_decay: number of iterations passed for decreasing the learning rate
            :param lr_gamma: proportion of learning rate kept at each decrease. It can also be a set of rules defined by a list, e.g. lr_gamma = [[3000, 0.9], ..., [None, 0.8]] means 0.9 until iteration 3000, ..., 0.8 until the end.
            :param patience: number of epochs waiting for a possible performance increase before stopping training
            :param metric_check: name of the metric checked for early stoppping and LR decrease

            ####    Data processing parameters

            :param n_parallel_loaders: number of parallel data loaders allowed to work at the same time
            :param normalize: boolean indicating if we want to 0-1 normalize the image pixel values
            :param mean_substraction: boolean indicating if we want to substract the training mean
            :param data_augmentation: boolean indicating if we want to perform data augmentation (always False on validation)
            :param shuffle: apply shuffling on training data at the beginning of each epoch.

            ####    Other parameters

            :param save_model: number of iterations between each model backup
        """

        # Check input parameters and recover default values if needed

        default_params = {'n_epochs': 1, 'batch_size': 50,
                          'maxlen': 100,  # sequence learning parameters (BeamSearch)
                          'homogeneous_batches': False,
                          'joint_batches': 4,
                          'epochs_for_save': 1,
                          'num_iterations_val': None,
                          'n_parallel_loaders': 8,
                          'normalize': False,
                          'mean_substraction': True,
                          'data_augmentation': True,
                          'verbose': 1, 'eval_on_sets': ['val'],
                          'reload_epoch': 0,
                          'extra_callbacks': [],
                          'shuffle': True,
                          'epoch_offset': 0,
                          'patience': 0,
                          'metric_check': None,
                          'eval_on_epochs': True,
                          'each_n_epochs': 1,
                          'start_eval_on_epoch':0, # early stopping parameters
                          'lr_decay': None, # LR decay parameters
                          'lr_gamma': 0.1}
        params = self.checkParameters(parameters, default_params)
        save_params = copy.copy(params)
        del save_params['extra_callbacks']
        self.training_parameters.append(save_params)
        self.__train_from_samples(x, y, params, class_weight=class_weight, sample_weight=sample_weight)
        if params['verbose'] > 0:
            logging.info("<<< Finished training model >>>")

    def __train(self, ds, params, state=dict()):

        if params['verbose'] > 0:
            logging.info("Training parameters: " + str(params))

        # initialize state
        state['samples_per_epoch'] = ds.len_train
        state['n_iterations_per_epoch'] = int(math.ceil(float(state['samples_per_epoch']) / params['batch_size']))

        # Prepare callbacks
        callbacks = []
        ## Callbacks order:

        # Extra callbacks (e.g. evaluation)
        callbacks += params['extra_callbacks']

        # LR reducer
        if params.get('lr_decay') is not None:
            callback_lr_reducer = LearningRateReducer(lr_decay=params['lr_decay'], reduce_rate=params['lr_gamma'])
            callbacks.append(callback_lr_reducer)

        # Early stopper
        if params.get('metric_check') is not None:
            callback_early_stop = EarlyStopping(self,
                                                patience=params['patience'],
                                                metric_check=params['metric_check'],
                                                eval_on_epochs=params['eval_on_epochs'],
                                                each_n_epochs=params['each_n_epochs'],
                                                start_eval_on_epoch=params['start_eval_on_epoch'])
            callbacks.append(callback_early_stop)

        # Store model
        if params['epochs_for_save'] >= 0:
            callback_store_model = StoreModelWeightsOnEpochEnd(self, saveModel, params['epochs_for_save'])
            callbacks.append(callback_store_model)

        # Prepare data generators
        if params['homogeneous_batches']:
            train_gen = Homogeneous_Data_Batch_Generator('train',
                                                         self,
                                                         ds,
                                                         state['n_iterations_per_epoch'],
                                                         batch_size=params['batch_size'],
                                                         joint_batches=params['joint_batches'],
                                                         normalization=params['normalize'],
                                                         data_augmentation=params['data_augmentation'],
                                                         mean_substraction=params['mean_substraction']).generator()
        else:
            train_gen = Data_Batch_Generator('train', self, ds, state['n_iterations_per_epoch'],
                                             batch_size=params['batch_size'],
                                             normalization=params['normalize'],
                                             data_augmentation=params['data_augmentation'],
                                             mean_substraction=params['mean_substraction'],
                                             shuffle=params['shuffle']).generator()
        # Are we going to validate on 'val' data?
        if 'val' in params['eval_on_sets']:

            # Calculate how many validation interations are we going to perform per test
            n_valid_samples = ds.len_val
            if params['num_iterations_val'] == None:
                params['num_iterations_val'] = int(math.ceil(float(n_valid_samples) / params['batch_size']))

            # prepare data generator
            val_gen = Data_Batch_Generator('val', self, ds, params['num_iterations_val'],
                                           batch_size=params['batch_size'],
                                           normalization=params['normalize'],
                                           data_augmentation=False,
                                           mean_substraction=params['mean_substraction']).generator()
        else:
            val_gen = None
            n_valid_samples = None

        # Train model
        self.model.fit_generator(train_gen,
                                 validation_data=val_gen,
                                 nb_val_samples=n_valid_samples,
                                 samples_per_epoch=state['samples_per_epoch'],
                                 nb_epoch=params['n_epochs'],
                                 max_q_size=params['n_parallel_loaders'],
                                 verbose=params['verbose'],
                                 callbacks=callbacks,
                                 initial_epoch=params['epoch_offset'])

    def __train_from_samples(self, x, y, params, class_weight=None, sample_weight=None, state=dict()):

        if params['verbose'] > 0:
            logging.info("Training parameters: " + str(params))
        callbacks = []
        ## Callbacks order:

        # Extra callbacks (e.g. evaluation)
        callbacks += params['extra_callbacks']

        # LR reducer
        if params.get('lr_decay') is not None:
            callback_lr_reducer = LearningRateReducer(lr_decay=params['lr_decay'], reduce_rate=params['lr_gamma'])
            callbacks.append(callback_lr_reducer)

        # Early stopper
        if params.get('metric_check') is not None:
            callback_early_stop = EarlyStopping(self,
                                                patience=params['patience'],
                                                metric_check=params['metric_check'],
                                                eval_on_epochs=params['eval_on_epochs'],
                                                each_n_epochs=params['each_n_epochs'],
                                                start_eval_on_epoch=params['start_eval_on_epoch'])
            callbacks.append(callback_early_stop)

        # Store model
        if params['epochs_for_save'] >= 0:
            callback_store_model = StoreModelWeightsOnEpochEnd(self, saveModel, params['epochs_for_save'])
            callbacks.append(callback_store_model)

        # Train model
        self.model.fit(x,
                       y,
                       batch_size=min(params['batch_size'], len(x)),
                       nb_epoch=params['n_epochs'],
                       verbose=params['verbose'],
                       callbacks=callbacks,
                       validation_data=None,
                       validation_split=params.get('val_split', 0.),
                       shuffle=params['shuffle'],
                       class_weight=class_weight,
                       sample_weight=sample_weight,
                       initial_epoch=params['epoch_offset'])

    def __train_deprecated(self, ds, params, state=dict(), out_name=None):
        """
            Main training function, which will only be called from self.trainNet(...) or self.resumeTrainNet(...)
        """
        scores_train = []
        losses_train = []
        top_scores_train = []

        logging.info("Training parameters: " + str(params))

        # Calculate how many iterations are we going to perform
        if not state.has_key('n_iterations_per_epoch'):
            state['n_iterations_per_epoch'] = int(math.ceil(float(ds.len_train) / params['batch_size']))
            state['count_iteration'] = 0
            state['epoch'] = 0
            state['it'] = -1
        else:
            state['count_iteration'] -= 1
            state['it'] -= 1

        # Calculate how many validation interations are we going to perform per test
        if params['num_iterations_val'] == None:
            params['num_iterations_val'] = int(math.ceil(float(ds.len_val) / params['batch_size']))

        # Apply params['n_epochs'] for training
        for state['epoch'] in range(state['epoch'], params['n_epochs']):
            logging.info("<<< Starting epoch " + str(state['epoch'] + 1) + "/" + str(params['n_epochs']) + " >>>")

            # Shuffle the training samples before each epoch
            ds.shuffleTraining()

            # Initialize queue of parallel data loaders
            t_queue = []
            for t_ind in range(state['n_iterations_per_epoch']):
                t = ThreadDataLoader(retrieveXY, ds, 'train', params['batch_size'],
                                     params['normalize'], params['mean_substraction'], params['data_augmentation'])
                if t_ind > state['it'] and t_ind < params['n_parallel_loaders'] + state['it'] + 1:
                    t.start()
                t_queue.append(t)

            for state['it'] in range(state['it'] + 1, state['n_iterations_per_epoch']):
                state['count_iteration'] += 1

                # Recovers a pre-loaded batch of data
                time_load = time.time() * 1000.0
                t = t_queue[state['it']]
                t.join()
                time_load = time.time() * 1000.0 - time_load
                if params['verbose'] > 0:
                    logging.info("DEBUG: Batch loaded in %0.8s ms" % str(time_load))

                if t.resultOK:
                    X_batch = t.X
                    Y_batch = t.Y
                else:
                    if params['verbose'] > 1:
                        logging.info("DEBUG: Exception occurred.")
                    exc_type, exc_obj, exc_trace = t.exception
                    # deal with the exception
                    print exc_type, exc_obj
                    print exc_trace
                    raise Exception('Exception occurred in ThreadLoader.')
                t_queue[state['it']] = None
                if state['it'] + params['n_parallel_loaders'] < state['n_iterations_per_epoch']:
                    if params['verbose'] > 1:
                        logging.info("DEBUG: Starting new thread loader.")
                    t = t_queue[state['it'] + params['n_parallel_loaders']]
                    t.start()

                # Forward and backward passes on the current batch
                time_train = time.time() * 1000.0
                if isinstance(self.model, Sequential):
                    [X_batch, Y_batch] = self._prepareSequentialData(X_batch, Y_batch)
                    loss = self.model.train_on_batch(X_batch, Y_batch)
                    loss = loss[0]
                    [score, top_score] = self._getSequentialAccuracy(Y_batch, self.model.predict_on_batch(X_batch)[0])
                elif isinstance(self.model, Model):
                    t1 = time.time() * 1000.0
                    [X_batch, Y_batch] = self._prepareSequentialData(X_batch, Y_batch)
                    if params['verbose'] > 1:
                        t2 = time.time() * 1000.0
                        logging.info("DEBUG: Data ready for training (%0.8s ms)." % (t2 - t1))
                    loss = self.model.train_on_batch(X_batch, Y_batch)
                    if params['verbose'] > 1:
                        t3 = time.time() * 1000.0
                        logging.info("DEBUG: Training forward & backward passes performed (%0.8s ms)." % (t3 - t2))
                    loss = loss[0]
                    score = loss[1]
                    # [score, top_score] = self._getSequentialAccuracy(Y_batch, self.model.predict_on_batch(X_batch))
                else:
                    [data, last_output] = self._prepareGraphData(X_batch, Y_batch)
                    loss = self.model.train_on_batch(data)
                    loss = loss[0]
                    score = self._getGraphAccuracy(data, self.model.predict_on_batch(data))
                    top_score = score[1]
                    score = score[0]
                    if out_name:
                        score = score[out_name]
                        top_score = top_score[out_name]
                    else:
                        score = score[last_output]
                        top_score = top_score[last_output]
                time_train = time.time() * 1000.0 - time_train
                if params['verbose'] > 0:
                    logging.info("DEBUG: Train on batch performed in %0.8s ms" % str(time_train))

                scores_train.append(float(score))
                losses_train.append(float(loss))
                top_scores_train.append(float(top_score))

                # Report train info
                if state['count_iteration'] % params['report_iter'] == 0:
                    loss = np.mean(losses_train)
                    score = np.mean(scores_train)
                    top_score = np.mean(top_scores_train)

                    logging.info("Train - Iteration: " + str(state['count_iteration']) + "   (" + str(
                        state['count_iteration'] * params['batch_size']) + " samples seen)")
                    logging.info("\tTrain loss: " + str(loss))
                    logging.info("\tTrain accuracy: " + str(score))
                    logging.info("\tTrain accuracy top-5: " + str(top_score))

                    self.log('train', 'iteration', state['count_iteration'])
                    self.log('train', 'loss', loss)
                    self.log('train', 'accuracy', score)
                    try:
                        self.log('train', 'accuracy top-5', top_score)
                    except:
                        pass

                    scores_train = []
                    losses_train = []
                    top_scores_train = []

                # Test network on validation set
                if state['count_iteration'] > 0 and state['count_iteration'] % params['iter_for_val'] == 0:
                    logging.info("Applying validation...")
                    scores = []
                    losses = []
                    top_scores = []

                    t_val_queue = []
                    for t_ind in range(params['num_iterations_val']):
                        t = ThreadDataLoader(retrieveXY, ds, 'val', params['batch_size'],
                                             params['normalize'], params['mean_substraction'], False)
                        if t_ind < params['n_parallel_loaders']:
                            t.start()
                        t_val_queue.append(t)

                    for it_val in range(params['num_iterations_val']):

                        # Recovers a pre-loaded batch of data
                        t_val = t_val_queue[it_val]
                        t_val.join()
                        if t_val.resultOK:
                            X_val = t_val.X
                            Y_val = t_val.Y
                        else:
                            exc_type, exc_obj, exc_trace = t.exception
                            # deal with the exception
                            print exc_type, exc_obj
                            print exc_trace
                            raise Exception('Exception occurred in ThreadLoader.')
                        t_val_queue[it_val] = None
                        if it_val + params['n_parallel_loaders'] < params['num_iterations_val']:
                            t_val = t_val_queue[it_val + params['n_parallel_loaders']]
                            t_val.start()

                        # Forward prediction pass
                        if isinstance(self.model, Sequential) or isinstance(self.model, Model):
                            [X_val, Y_val] = self._prepareSequentialData(X_val, Y_val)
                            loss = self.model.test_on_batch(X_val, Y_val, accuracy=False)
                            loss = loss[0]
                            [score, top_score] = self._getSequentialAccuracy(Y_val,
                                                                             self.model.predict_on_batch(X_val)[0])
                        else:
                            [data, last_output] = self._prepareGraphData(X_val, Y_val)
                            loss = self.model.test_on_batch(data)
                            loss = loss[0]
                            score = self._getGraphAccuracy(data, self.model.predict_on_batch(data))
                            top_score = score[1]
                            score = score[0]
                            if out_name:
                                score = score[out_name]
                                top_score = top_score[out_name]
                            else:
                                score = score[last_output]
                                top_score = top_score[last_output]
                        losses.append(float(loss))
                        scores.append(float(score))
                        top_scores.append(float(top_score))

                    ds.resetCounters(set_name='val')
                    logging.info("Val - Iteration: " + str(state['count_iteration']))
                    loss = np.mean(losses)
                    logging.info("\tValidation loss: " + str(loss))
                    score = np.mean(scores)
                    logging.info("\tValidation accuracy: " + str(score))
                    top_score = np.mean(top_scores)
                    logging.info("\tValidation accuracy top-5: " + str(top_score))

                    self.log('val', 'iteration', state['count_iteration'])
                    self.log('val', 'loss', loss)
                    self.log('val', 'accuracy', score)
                    try:
                        self.log('val', 'accuracy top-5', top_score)
                    except:
                        pass

                    self.plot()

                # Save the model
                if state['count_iteration'] % params['save_model'] == 0:
                    self.training_state = state
                    saveModel(self, state['count_iteration'])

                # Decrease the current learning rate
                if state['count_iteration'] % params['lr_decay'] == 0:
                    # Check if we have a set of rules
                    if isinstance(params['lr_gamma'], list):
                        # Check if the current lr_gamma rule is still valid
                        if params['lr_gamma'][0][0] == None or params['lr_gamma'][0][0] > state['count_iteration']:
                            lr_gamma = params['lr_gamma'][0][1]
                        else:
                            # Find next valid lr_gamma
                            while params['lr_gamma'][0][0] != None and params['lr_gamma'][0][0] <= state[
                                'count_iteration']:
                                params['lr_gamma'].pop(0)
                            lr_gamma = params['lr_gamma'][0][1]
                    # Else, we have a single lr_gamma for the whole training
                    else:
                        lr_gamma = params['lr_gamma']
                    lr = self.lr * lr_gamma
                    momentum = 1 - lr
                    self.setOptimizer(lr, momentum)

            self.training_state = state
            state['it'] = -1  # start again from the first iteration of the next epoch

    def testNet(self, ds, parameters, out_name=None):

        # Check input parameters and recover default values if needed
        default_params = {'batch_size': 50, 'n_parallel_loaders': 8, 'normalize': False,
                          'mean_substraction': True};
        params = self.checkParameters(parameters, default_params)
        self.testing_parameters.append(copy.copy(params))

        logging.info("<<< Testing model >>>")

        # Calculate how many test interations are we going to perform
        n_samples = ds.len_test
        num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))

        # Test model
        # We won't use an Homogeneous_Batch_Generator for testing
        data_gen = Data_Batch_Generator('test', self, ds, num_iterations,
                                        batch_size=params['batch_size'],
                                        normalization=params['normalize'],
                                        data_augmentation=False,
                                        mean_substraction=params['mean_substraction']).generator()

        out = self.model.evaluate_generator(data_gen,
                                            val_samples=n_samples,
                                            max_q_size=params['n_parallel_loaders'])

        # Display metrics results
        for name, o in zip(self.model.metrics_names, out):
            logging.info('test ' + name + ': %0.8s' % o)

            # loss_all = out[0]
            # loss_ecoc = out[1]
            # loss_final = out[2]
            # acc_ecoc = out[3]
            # acc_final = out[4]
            # logging.info('Test loss: %0.8s' % loss_final)
            # logging.info('Test accuracy: %0.8s' % acc_final)

    def testNet_deprecated(self, ds, parameters, out_name=None):
        """
            Applies a complete round of tests using the test set in the provided Dataset instance.

            :param out_name: name of the output node that will be used to evaluate the network accuracy. Only applicable for Graph models.

            The available (optional) testing parameters are the following ones:

            :param batch_size: size of the batch (number of images) applied on each interation

            ####    Data processing parameters

            :param n_parallel_loaders: number of parallel data loaders allowed to work at the same time
            :param normalization: boolean indicating if we want to 0-1 normalize the image pixel values
            :param mean_substraction: boolean indicating if we want to substract the training mean
        """
        # Check input parameters and recover default values if needed
        default_params = {'batch_size': 50, 'n_parallel_loaders': 8, 'normalize': False, 'mean_substraction': True};
        params = self.checkParameters(parameters, default_params)
        self.testing_parameters.append(copy.copy(params))

        logging.info("<<< Testing model >>>")

        numIterationsTest = int(math.ceil(float(ds.len_test) / params['batch_size']))
        scores = []
        losses = []
        top_scores = []

        t_test_queue = []
        for t_ind in range(numIterationsTest):
            t = ThreadDataLoader(retrieveXY, ds, 'test', params['batch_size'],
                                 params['normalize'], params['mean_substraction'], False)
            if t_ind < params['n_parallel_loaders']:
                t.start()
            t_test_queue.append(t)

        for it_test in range(numIterationsTest):

            t_test = t_test_queue[it_test]
            t_test.join()
            if t_test.resultOK:
                X_test = t_test.X
                Y_test = t_test.Y
            else:
                exc_type, exc_obj, exc_trace = t.exception
                # deal with the exception
                print exc_type, exc_obj
                print exc_trace
                raise Exception('Exception occurred in ThreadLoader.')
            t_test_queue[it_test] = None
            if it_test + params['n_parallel_loaders'] < numIterationsTest:
                t_test = t_test_queue[it_test + params['n_parallel_loaders']]
                t_test.start()

            if isinstance(self.model, Sequential) or isinstance(self.model, Model):
                # (loss, score) = self.model.evaluate(X_test, Y_test, show_accuracy=True)
                [X_test, Y_test] = self._prepareSequentialData(X_test, Y_test)
                loss = self.model.test_on_batch(X_test, Y_test, accuracy=False)
                loss = loss[0]
                [score, top_score] = self._getSequentialAccuracy(Y_test, self.model.predict_on_batch(X_test)[0])
            else:
                [data, last_output] = self._prepareGraphData(X_test, Y_test)
                loss = self.model.test_on_batch(data)
                loss = loss[0]
                score = self._getGraphAccuracy(data, self.model.predict_on_batch(data))
                top_score = score[1]
                score = score[0]
                if out_name:
                    score = score[out_name]
                    top_score = top_score[out_name]
                else:
                    score = score[last_output]
                    top_score = top_score[last_output]
            losses.append(float(loss))
            scores.append(float(score))
            top_scores.append(float(top_score))

        ds.resetCounters(set_name='test')
        logging.info("\tTest loss: " + str(np.mean(losses)))
        logging.info("\tTest accuracy: " + str(np.mean(scores)))
        logging.info("\tTest accuracy top-5: " + str(np.mean(top_scores)))

    def testNetSamples(self, X, batch_size=50):
        """
            Applies a forward pass on the samples provided and returns the predicted classes and probabilities.
        """
        classes = self.model.predict_classes(X, batch_size=batch_size)
        probs = self.model.predict_proba(X, batch_size=batch_size)

        return [classes, probs]

    def testOnBatch(self, X, Y, accuracy=True, out_name=None):
        """
            Applies a test on the samples provided and returns the resulting loss and accuracy (if True).

            :param out_name: name of the output node that will be used to evaluate the network accuracy. Only applicable for Graph models.
        """
        n_samples = X.shape[1]
        if isinstance(self.model, Sequential) or isinstance(self.model, Model):
            [X, Y] = self._prepareSequentialData(X, Y)
            loss = self.model.test_on_batch(X, Y, accuracy=False)
            loss = loss[0]
            if accuracy:
                [score, top_score] = self._getSequentialAccuracy(Y, self.model.predict_on_batch(X)[0])
                return loss, score, top_score, n_samples
            return loss, n_samples
        else:
            [data, last_output] = self._prepareGraphData(X, Y)
            loss = self.model.test_on_batch(data)
            loss = loss[0]
            if accuracy:
                score = self._getGraphAccuracy(data, self.model.predict_on_batch(data))
                top_score = score[1]
                score = score[0]
                if out_name:
                    score = score[out_name]
                    top_score = top_score[out_name]
                else:
                    score = score[last_output]
                    top_score = top_score[last_output]
                return loss, score, top_score, n_samples
            return loss, n_samples

    # ------------------------------------------------------- #
    #       PREDICTION FUNCTIONS
    #           Functions for making prediction on input samples
    # ------------------------------------------------------- #
    def predict_cond(self, X, states_below, params, ii):
        """
        Returns predictions on batch given the (static) input X and the current history (states_below) at time-step ii.
        WARNING!: It's assumed that the current history (state_below) is the last input of the model! See Dataset class for more information
        :param X: Input context
        :param states_below: Batch of partial hypotheses
        :param params: Decoding parameters
        :param ii: Decoding time-step
        :return: Network predictions at time-step ii
        """
        in_data = {}
        n_samples = states_below.shape[0]

        ##########################################
        # Choose model to use for sampling
        ##########################################
        model = self.model
        for model_input in params['model_inputs']:
            if X[model_input].shape[0] == 1:
                in_data[model_input] = np.repeat(X[model_input], n_samples, axis=0)
        in_data[params['model_inputs'][params['state_below_index']]] = states_below

        ##########################################
        # Recover output identifiers
        ##########################################
        # in any case, the first output of the models must be the next words' probabilities
        pick_idx = -1
        output_ids_list = params['model_outputs']
        pick_idx = ii

        ##########################################
        # Apply prediction on current timestep
        ##########################################
        if params['batch_size'] >= n_samples:  # The model inputs beam will fit into one batch in memory
            out_data = model.predict_on_batch(in_data)
        else:  # It is possible that the model inputs don't fit into one single batch: Make one-sample-sized batches
            for i in range(n_samples):
                aux_in_data = {}
                for k, v in in_data.iteritems():
                    aux_in_data[k] = np.expand_dims(v[i], axis=0)
                predicted_out = model.predict_on_batch(aux_in_data)
                if i == 0:
                    out_data = predicted_out
                else:
                    if len(output_ids_list) > 1:
                        for iout in range(len(output_ids_list)):
                            out_data[iout] = np.vstack((out_data[iout], predicted_out[iout]))
                    else:
                        out_data = np.vstack((out_data, predicted_out))

        ##########################################
        # Get outputs
        ##########################################

        if len(output_ids_list) > 1:
            all_data = {}
            for output_id in range(len(output_ids_list)):
                all_data[output_ids_list[output_id]] = out_data[output_id]
            all_data[output_ids_list[0]] = np.array(all_data[output_ids_list[0]])[:, pick_idx, :]
        else:
            all_data = {output_ids_list[0]: np.array(out_data)[:, pick_idx, :]}
        probs = all_data[output_ids_list[0]]

        ##########################################
        # Define returned data
        ##########################################
        return probs

    def predict_cond_optimized(self, X, states_below, params, ii, prev_out):
        """
        Returns predictions on batch given the (static) input X and the current history (states_below) at time-step ii.
        WARNING!: It's assumed that the current history (state_below) is the last input of the model!
        See Dataset class for more information
        :param X: Input context
        :param states_below: Batch of partial hypotheses
        :param params: Decoding parameters
        :param ii: Decoding time-step
        :param prev_out: output from the previous timestep, which will be reused by self.model_next
        (only applicable if beam search specific models self.model_init and self.model_next models are defined)
        :return: Network predictions at time-step ii
        """
        in_data = {}
        n_samples = states_below.shape[0]

        ##########################################
        # Choose model to use for sampling
        ##########################################
        if ii == 0:
            model = self.model_init
        else:
            model = self.model_next
        ##########################################
        # Get inputs
        ##########################################

        if ii > 1:  # timestep > 1 (model_next to model_next)
            for idx, next_out_name in enumerate(self.ids_outputs_next):
                if idx == 0:
                    in_data[self.ids_inputs_next[0]] = states_below[:, -1].reshape(n_samples, 1)
                if idx > 0:  # first output must be the output probs.
                    if next_out_name in self.matchings_next_to_next.keys():
                        next_in_name = self.matchings_next_to_next[next_out_name]
                        if prev_out[idx].shape[0] == 1:
                            prev_out[idx] = np.repeat(prev_out[idx], n_samples, axis=0)
                        in_data[next_in_name] = prev_out[idx]
        elif ii == 0:  # first timestep
            for model_input in params['model_inputs']:#[:-1]:
                if X[model_input].shape[0] == 1:
                    in_data[model_input] = np.repeat(X[model_input], n_samples, axis=0)
            in_data[params['model_inputs'][params['state_below_index']]] = states_below.reshape(n_samples, 1)
        elif ii == 1:  # timestep == 1 (model_init to model_next)
            for idx, init_out_name in enumerate(self.ids_outputs_init):
                if idx == 0:
                    in_data[self.ids_inputs_next[0]] = states_below[:, -1].reshape(n_samples, 1)
                if idx > 0:  # first output must be the output probs.
                    if init_out_name in self.matchings_init_to_next.keys():
                        next_in_name = self.matchings_init_to_next[init_out_name]
                        if prev_out[idx].shape[0] == 1:
                            prev_out[idx] = np.repeat(prev_out[idx], n_samples, axis=0)
                        in_data[next_in_name] = prev_out[idx]

        ##########################################
        # Recover output identifiers
        ##########################################
        # in any case, the first output of the models must be the next words' probabilities
        pick_idx = 0
        if ii == 0:  # optimized search model (model_init case)
            output_ids_list = self.ids_outputs_init
        else:  # optimized search model (model_next case)
            output_ids_list = self.ids_outputs_next

        ##########################################
        # Apply prediction on current timestep
        ##########################################
        if params['batch_size'] >= n_samples:  # The model inputs beam will fit into one batch in memory
            out_data = model.predict_on_batch(in_data)
        else:  # It is possible that the model inputs don't fit into one single batch: Make one-sample-sized batches
            for i in range(n_samples):
                aux_in_data = {}
                for k, v in in_data.iteritems():
                    aux_in_data[k] = np.expand_dims(v[i], axis=0)
                predicted_out = model.predict_on_batch(aux_in_data)
                if i == 0:
                    out_data = predicted_out
                else:
                    if len(output_ids_list) > 1:
                        for iout in range(len(output_ids_list)):
                            out_data[iout] = np.vstack((out_data[iout], predicted_out[iout]))
                    else:
                        out_data = np.vstack((out_data, predicted_out))
        ##########################################
        # Get outputs
        ##########################################

        if len(output_ids_list) > 1:
            all_data = {}
            for output_id in range(len(output_ids_list)):
                all_data[output_ids_list[output_id]] = out_data[output_id]
            all_data[output_ids_list[0]] = np.array(all_data[output_ids_list[0]])[:, pick_idx, :]
        else:
            all_data = {output_ids_list[0]: np.array(out_data)[:, pick_idx, :]}
        probs = all_data[output_ids_list[0]]

        ##########################################
        # Define returned data
        ##########################################
        return [probs, out_data]

    def beam_search(self, X, params, null_sym=2):
        """
        Beam search method for Cond models.
        (https://en.wikibooks.org/wiki/Artificial_Intelligence/Search/Heuristic_search/Beam_search)
        The algorithm in a nutshell does the following:

        1. k = beam_size
        2. open_nodes = [[]] * k
        3. while k > 0:

            3.1. Given the inputs, get (log) probabilities for the outputs.

            3.2. Expand each open node with all possible output.

            3.3. Prune and keep the k best nodes.

            3.4. If a sample has reached the <eos> symbol:

                3.4.1. Mark it as final sample.

                3.4.2. k -= 1

            3.5. Build new inputs (state_below) and go to 1.

        4. return final_samples, final_scores

        :param X: Model inputs
        :param params: Search parameters
        :param null_sym: <null> symbol
        :return: UNSORTED list of [k_best_samples, k_best_scores] (k: beam size)
        """
        k = params['beam_size']
        samples = []
        sample_scores = []
        pad_on_batch = params['pad_on_batch']
        dead_k = 0  # samples that reached eos
        live_k = 1  # samples that did not yet reached eos
        hyp_samples = [[]] * live_k
        hyp_scores = np.zeros(live_k).astype('float32')
        if params['pos_unk']:
            sample_alphas = []
            hyp_alphas = [[]] * live_k
        # we must include an additional dimension if the input for each timestep are all the generated "words_so_far"
        if params['words_so_far']:
            if k > params['maxlen']:
                raise NotImplementedError(
                    "BEAM_SIZE can't be higher than MAX_OUTPUT_TEXT_LEN on the current implementation.")
            state_below = np.asarray([[null_sym]] * live_k) if pad_on_batch else np.asarray(
                [np.zeros((params['maxlen'], params['maxlen']))] * live_k)
        else:
            state_below = np.asarray([null_sym] * live_k) if pad_on_batch else np.asarray(
                [np.zeros(params['maxlen'])] * live_k)

        prev_out = None
        for ii in xrange(params['maxlen']):
            # for every possible live sample calc prob for every possible label
            if params['optimized_search']:  # use optimized search model if available
                [probs, prev_out] = self.predict_cond_optimized(X, state_below, params, ii, prev_out)
                if params['pos_unk']:
                    alphas = prev_out[-1][0]  # Shape: (k, n_steps)
                    prev_out = prev_out[:-1]
            else:
                probs = self.predict_cond(X, state_below, params, ii)
            # total score for every sample is sum of -log of word prb
            cand_scores = np.array(hyp_scores)[:, None] - np.log(probs)
            cand_flat = cand_scores.flatten()
            # Find the best options by calling argsort of flatten array
            ranks_flat = cand_flat.argsort()[:(k - dead_k)]
            # Decypher flatten indices
            voc_size = probs.shape[1]
            trans_indices = ranks_flat / voc_size  # index of row
            word_indices = ranks_flat % voc_size  # index of col
            costs = cand_flat[ranks_flat]
            # Form a beam for the next iteration
            new_hyp_samples = []
            new_trans_indices = []
            new_hyp_scores = np.zeros(k - dead_k).astype('float32')
            if params['pos_unk']:
                new_hyp_alphas = []
            for idx, [ti, wi] in enumerate(zip(trans_indices, word_indices)):
                new_hyp_samples.append(hyp_samples[ti] + [wi])
                new_trans_indices.append(ti)
                new_hyp_scores[idx] = copy.copy(costs[idx])
                if params['pos_unk']:
                    new_hyp_alphas.append(hyp_alphas[ti] + [alphas[ti]])

            # check the finished samples
            new_live_k = 0
            hyp_samples = []
            hyp_scores = []
            hyp_alphas = []
            indices_alive = []
            for idx in xrange(len(new_hyp_samples)):
                if new_hyp_samples[idx][-1] == 0:  # finished sample
                    samples.append(new_hyp_samples[idx])
                    sample_scores.append(new_hyp_scores[idx])
                    if params['pos_unk']:
                        sample_alphas.append(new_hyp_alphas[idx])
                    dead_k += 1
                else:
                    indices_alive.append(new_trans_indices[idx])
                    new_live_k += 1
                    hyp_samples.append(new_hyp_samples[idx])
                    hyp_scores.append(new_hyp_scores[idx])
                    if params['pos_unk']:
                        hyp_alphas.append(new_hyp_alphas[idx])
            hyp_scores = np.array(hyp_scores)
            live_k = new_live_k

            if new_live_k < 1:
                break
            if dead_k >= k:
                break
            state_below = np.asarray(hyp_samples, dtype='int64')

            # we must include an additional dimension if the input for each timestep are all the generated words so far
            if pad_on_batch:
                state_below = np.hstack((np.zeros((state_below.shape[0], 1), dtype='int64') + null_sym, state_below))
                if params['words_so_far']:
                    state_below = np.expand_dims(state_below, axis=0)
            else:
                state_below = np.hstack((np.zeros((state_below.shape[0], 1), dtype='int64'), state_below,
                                         np.zeros((state_below.shape[0],
                                                   max(params['maxlen'] - state_below.shape[1] - 1, 0)),
                                                  dtype='int64')))

                if params['words_so_far']:
                    state_below = np.expand_dims(state_below, axis=0)
                    state_below = np.hstack((state_below,
                                             np.zeros((state_below.shape[0], params['maxlen'] - state_below.shape[1],
                                                       state_below.shape[2]))))

            if params['optimized_search'] and ii > 0:
                # filter next search inputs w.r.t. remaining samples
                for idx_vars in range(len(prev_out)):
                    prev_out[idx_vars] = prev_out[idx_vars][indices_alive]

        # dump every remaining one
        if live_k > 0:
            for idx in xrange(live_k):
                samples.append(hyp_samples[idx])
                sample_scores.append(hyp_scores[idx])
                if params['pos_unk']:
                    sample_alphas.append(hyp_alphas[idx])
        if params['pos_unk']:
            return samples, sample_scores, sample_alphas
        else:
            return samples, sample_scores

    def BeamSearchNet(self, ds, parameters):
        """
        DEPRECATED, use predictBeamSearchNet() instead.
        """
        print "WARNING!: deprecated function, use predictBeamSearchNet() instead"
        return self.predictBeamSearchNet(ds, parameters)

    def predictBeamSearchNet(self, ds, parameters={}):
        """
        Approximates by beam search the best predictions of the net on the dataset splits chosen.

        :param batch_size: size of the batch
        :param n_parallel_loaders: number of parallel data batch loaders
        :param normalization: apply data normalization on images/features or not (only if using images/features as input)
        :param mean_substraction: apply mean data normalization on images or not (only if using images as input)
        :param predict_on_sets: list of set splits for which we want to extract the predictions ['train', 'val', 'test']
        :param optimized_search: boolean indicating if the used model has the optimized Beam Search implemented (separate self.model_init and self.model_next models for reusing the information from previous timesteps).
        The following attributes must be inserted to the model when building an optimized search model:
        
            * ids_inputs_init: list of input variables to model_init (must match inputs to conventional model)
            * ids_outputs_init: list of output variables of model_init (model probs must be the first output)
            * ids_inputs_next: list of input variables to model_next (previous word must be the first input)
            * ids_outputs_next: list of output variables of model_next (model probs must be the first output and the number of out variables must match the number of in variables)
            * matchings_init_to_next: dictionary from 'ids_outputs_init' to 'ids_inputs_next'
            * matchings_next_to_next: dictionary from 'ids_outputs_next' to 'ids_inputs_next'

        :param temporally_linked: boolean indicating if the outputs from a sample are the inputs of the following one
        The following attributes must be inserted to the model when building a temporally_linked model:

            * matchings_sample_to_next_sample:
            * ids_temporally_linked_inputs:

        :returns predictions: dictionary with set splits as keys and matrices of predictions as values.
        """

        # Check input parameters and recover default values if needed
        default_params = {'batch_size': 50, 'n_parallel_loaders': 8, 'beam_size': 5,
                          'normalize': False, 'mean_substraction': True,
                          'predict_on_sets': ['val'], 'maxlen': 20, 'n_samples': -1,
                          'model_inputs': ['source_text', 'state_below'],
                          'model_outputs': ['description'],
                          'dataset_inputs': ['source_text', 'state_below'],
                          'dataset_outputs': ['description'],
                          'alpha_factor': 1.0,
                          'sampling_type': 'max_likelihood',
                          'words_so_far': False,
                          'optimized_search': False,
                          'pos_unk': False,
                          'heuristic': 0,
                          'mapping': None,
                          'temporally_linked': False,
                          'link_index_id': 'link_index',
                          'state_below_index': -1
                          }
        params = self.checkParameters(parameters, default_params)

        # Check if the model is ready for applying an optimized search
        if params['optimized_search']:
            if 'matchings_init_to_next' not in dir(self) or \
                            'matchings_next_to_next' not in dir(self) or \
                            'ids_inputs_init' not in dir(self) or \
                            'ids_outputs_init' not in dir(self) or \
                            'ids_inputs_next' not in dir(self) or \
                            'ids_outputs_next' not in dir(self):
                raise Exception(
                    "The following attributes must be inserted to the model when building an optimized search model:\n",
                    "- matchings_init_to_next\n",
                    "- matchings_next_to_next\n",
                    "- ids_inputs_init\n",
                    "- ids_outputs_init\n",
                    "- ids_inputs_next\n",
                    "- ids_outputs_next\n")

        # Check if the model is ready for applying a temporally_linked search
        if params['temporally_linked']:
            if 'matchings_sample_to_next_sample' not in dir(self) or \
                            'ids_temporally_linked_inputs' not in dir(self):
                raise Exception(
                    "The following attributes must be inserted to the model when building a temporally_linked model:\n",
                    "- matchings_sample_to_next_sample\n",
                    "- ids_temporally_linked_inputs\n")

        predictions = dict()
        references = []
        sources_sampling = []
        for s in params['predict_on_sets']:
            logging.info("<<< Predicting outputs of " + s + " set >>>")

            # TODO: enable 'train' sampling on temporally-linked models
            if params['temporally_linked'] and s == 'train':
                logging.info('Sampling is currenly not implemented on the "train" set for temporally-linked models.')
                data_gen = -1
                data_gen_instance = -1
            else:

                assert len(params['model_inputs']) > 0, 'We need at least one input!'
                if not params['optimized_search']:  # use optimized search model if available
                    assert not params['pos_unk'], 'PosUnk is not supported with non-optimized beam search methods'

                params['pad_on_batch'] = ds.pad_on_batch[params['dataset_inputs'][params['state_below_index']]]

                if params['temporally_linked']:
                    previous_outputs = {}  # variable for storing previous outputs if using a temporally-linked model
                    for input_id in self.ids_temporally_linked_inputs:
                        previous_outputs[input_id] = dict()
                        previous_outputs[input_id][-1] = [ds.extra_words['<null>']]

                # Calculate how many iterations are we going to perform
                if params['n_samples'] < 1:
                    n_samples = eval("ds.len_" + s)
                    num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))

                    # Prepare data generator: We won't use an Homogeneous_Data_Batch_Generator here
                    data_gen_instance = Data_Batch_Generator(s, self, ds, num_iterations,
                                                    batch_size=params['batch_size'],
                                                    normalization=params['normalize'],
                                                    data_augmentation=False,
                                                    mean_substraction=params['mean_substraction'],
                                                    predict=True)
                    data_gen = data_gen_instance.generator()
                else:
                    n_samples = params['n_samples']
                    num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))

                    # Prepare data generator: We won't use an Homogeneous_Data_Batch_Generator here
                    data_gen_instance = Data_Batch_Generator(s, self, ds, num_iterations,
                                                    batch_size=params['batch_size'],
                                                    normalization=params['normalize'],
                                                    data_augmentation=False,
                                                    mean_substraction=params['mean_substraction'],
                                                    predict=False,
                                                    random_samples=n_samples,
                                                    temporally_linked=params['temporally_linked'])
                    data_gen = data_gen_instance.generator()

                if params['n_samples'] > 0:
                    references = []
                    sources_sampling = []
                best_samples = []
                if params['pos_unk']:
                    best_alphas = []
                    sources = []

                total_cost = 0
                sampled = 0
                start_time = time.time()
                eta = -1
                for j in range(num_iterations):
                    data = data_gen.next()
                    X = dict()
                    if params['n_samples'] > 0:
                        s_dict = {}
                        for input_id in params['model_inputs']:
                            X[input_id] = data[0][input_id]
                            s_dict[input_id] = X[input_id]
                        sources_sampling.append(s_dict)

                        Y = dict()
                        for output_id in params['model_outputs']:
                            Y[output_id] = data[1][output_id]
                    else:
                        s_dict = {}
                        for input_id in params['model_inputs']:
                            X[input_id] = data[input_id]
                            if params['pos_unk']:
                                s_dict[input_id] = X[input_id]
                        if params['pos_unk'] and not eval('ds.loaded_raw_' + s + '[0]'):
                            sources.append(s_dict)

                    for i in range(len(X[params['model_inputs'][0]])):
                        sampled += 1
                        sys.stdout.write('\r')
                        sys.stdout.write("Sampling %d/%d  -  ETA: %ds " % (sampled, n_samples, int(eta)))
                        sys.stdout.flush()
                        x = dict()

                        for input_id in params['model_inputs']:
                            if params['temporally_linked'] and input_id in self.ids_temporally_linked_inputs:
                                    link = int(X[params['link_index_id']][i])
                                    if link not in previous_outputs[input_id].keys():  # input to current sample was not processed yet
                                        link = -1
                                    prev_x = [ds.vocabulary[input_id]['idx2words'][w] for w in previous_outputs[input_id][link]]
                                    x[input_id] = ds.loadText([' '.join(prev_x)], ds.vocabulary[input_id],
                                                                 ds.max_text_len[input_id][s],
                                                                 ds.text_offset[input_id],
                                                                 fill=ds.fill_text[input_id],
                                                                 pad_on_batch=ds.pad_on_batch[input_id],
                                                                 words_so_far=ds.words_so_far[input_id],
                                                                 loading_X=True)[0]
                            else:
                                x[input_id] = np.asarray([X[input_id][i]])
                        if params['pos_unk']:
                            samples, scores, alphas = self.beam_search(x, params, null_sym=ds.extra_words['<null>'])
                        else:
                            samples, scores = self.beam_search(x, params, null_sym=ds.extra_words['<null>'])
                        if params['normalize']:
                            counts = [len(sample) ** params['alpha_factor'] for sample in samples]
                            scores = [co / cn for co, cn in zip(scores, counts)]
                        best_score = np.argmin(scores)
                        best_sample = samples[best_score]
                        best_samples.append(best_sample)
                        if params['pos_unk']:
                            best_alphas.append(np.asarray(alphas[best_score]))
                        total_cost += scores[best_score]
                        eta = (n_samples - sampled) * (time.time() - start_time) / sampled
                        if params['n_samples'] > 0:
                            for output_id in params['model_outputs']:
                                references.append(Y[output_id][i])

                        # store outputs for temporally-linked models
                        if params['temporally_linked']:
                            first_idx = max(0, data_gen_instance.first_idx)
                            # TODO: Make it more general
                            for (output_id, input_id) in self.matchings_sample_to_next_sample.iteritems():
                                # Get all words previous to the padding
                                previous_outputs[input_id][first_idx+sampled-1] = best_sample[:sum([int(elem > 0) for elem in best_sample])]

                sys.stdout.write('Total cost of the translations: %f \t Average cost of the translations: %f\n' % (
                    total_cost, total_cost / n_samples))
                sys.stdout.write('The sampling took: %f secs (Speed: %f sec/sample)\n' % ((time.time() - start_time), (
                    time.time() - start_time) / n_samples))

                sys.stdout.flush()

                if params['pos_unk']:
                    if eval('ds.loaded_raw_' + s + '[0]'):
                        sources = file2list(eval('ds.X_raw_' + s + '["raw_' + params['model_inputs'][0] + '"]'))
                    predictions[s] = (np.asarray(best_samples), np.asarray(best_alphas), sources)
                else:
                    predictions[s] = np.asarray(best_samples)
        del data_gen
        del data_gen_instance
        if params['n_samples'] < 1:
            return predictions
        else:
            return predictions, references, sources_sampling

    def predictNet(self, ds, parameters=dict(), postprocess_fun=None):
        '''
            Returns the predictions of the net on the dataset splits chosen. The input 'parameters' is a dict()
            which may contain the following parameters:

            :param batch_size: size of the batch
            :param n_parallel_loaders: number of parallel data batch loaders
            :param normalize: apply data normalization on images/features or not (only if using images/features as input)
            :param mean_substraction: apply mean data normalization on images or not (only if using images as input)
            :param predict_on_sets: list of set splits for which we want to extract the predictions ['train', 'val', 'test']

            Additional parameters:

            :param postprocess_fun : post-processing function applied to all predictions before returning the result. The output of the function must be a list of results, one per sample. If postprocess_fun is a list, the second element will be used as an extra input to the function.

            :returns predictions: dictionary with set splits as keys and matrices of predictions as values.
        '''

        # Check input parameters and recover default values if needed
        default_params = {'batch_size': 50,
                          'n_parallel_loaders': 8,
                          'normalize': False,
                          'mean_substraction': True,
                          'n_samples': None,
                          'predict_on_sets': ['val']}
        params = self.checkParameters(parameters, default_params)
        predictions = dict()
        for s in params['predict_on_sets']:
            predictions[s] = []

            logging.info("<<< Predicting outputs of " + s + " set >>>")
            # Calculate how many interations are we going to perform
            if params['n_samples'] is None:
                n_samples = eval("ds.len_" + s)
                num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))
                # Prepare data generator
                data_gen = Data_Batch_Generator(s,
                                                self,
                                                ds,
                                                num_iterations,
                                                batch_size=params['batch_size'],
                                                normalization=params['normalize'],
                                                data_augmentation=False,
                                                mean_substraction=params['mean_substraction'],
                                                predict=True).generator()

            else:
                n_samples = params['n_samples']
                num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))
                # Prepare data generator
                data_gen = Data_Batch_Generator(s,
                                                self,
                                                ds,
                                                num_iterations,
                                                batch_size=params['batch_size'],
                                                normalization=params['normalize'],
                                                data_augmentation=False,
                                                mean_substraction=params['mean_substraction'],
                                                predict=True,
                                                random_samples=n_samples).generator()
            # Predict on model
            if postprocess_fun is None:
                out = self.model.predict_generator(data_gen,
                                                   val_samples=n_samples,
                                                   max_q_size=params['n_parallel_loaders'])
                predictions[s] = out
            else:
                processed_samples = 0
                start_time = time.time()
                while processed_samples < n_samples:
                    out = self.model.predict_on_batch(data_gen.next())

                    # Apply post-processing function
                    if isinstance(postprocess_fun, list):
                        last_processed = min(processed_samples + params['batch_size'], n_samples)
                        out = postprocess_fun[0](out, postprocess_fun[1][processed_samples:last_processed])
                    else:
                        out = postprocess_fun(out)
                    predictions[s] += out

                    # Show progress
                    processed_samples += params['batch_size']
                    if processed_samples > n_samples:
                        processed_samples = n_samples
                    eta = (n_samples - processed_samples) * (time.time() - start_time) / processed_samples
                    sys.stdout.write('\r')
                    sys.stdout.write("Predicting %d/%d  -  ETA: %ds " % (processed_samples, n_samples, int(eta)))
                    sys.stdout.flush()

        return predictions

    def predictOnBatch(self, X, in_name=None, out_name=None, expand=False):
        """
            Applies a forward pass and returns the predicted values.
        """
        # Get desired input
        if in_name:
            X = copy.copy(X[in_name])

        # Expand input dimensions to 4
        if expand:
            while len(X.shape) < 4:
                X = np.expand_dims(X, axis=1)

        X = self.prepareData(X, None)[0]

        # Apply forward pass for prediction
        predictions = self.model.predict_on_batch(X)

        # Select output if indicated
        if isinstance(self.model, Model):  # Graph
            if out_name:
                predictions = predictions[out_name]
        elif isinstance(self.model, Sequential):  # Sequential
            predictions = predictions[0]

        return predictions

    # ------------------------------------------------------- #
    #       SCORING FUNCTIONS
    #           Functions for making scoring (x, y) samples
    # ------------------------------------------------------- #

    def score_cond_model(self, X, Y, params, null_sym=2):
        """
        Scoring for Cond models.
        :param X: Model inputs
        :param Y: Model outputs
        :param params: Search parameters
        :param null_sym: <null> symbol
        :return: UNSORTED list of [k_best_samples, k_best_scores] (k: beam size)
        """
        # we must include an additional dimension if the input for each timestep are all the generated "words_so_far"
        pad_on_batch = params['pad_on_batch']
        score = 0.0
        if params['words_so_far']:
            state_below = np.asarray([[null_sym]]) \
                if pad_on_batch else np.asarray([np.zeros((params['maxlen'], params['maxlen']))])
        else:
            state_below = np.asarray([null_sym]) \
                if pad_on_batch else np.asarray([np.zeros(params['maxlen'])])

        prev_out = None
        for ii in xrange(len(Y)):
            # for every possible live sample calc prob for every possible label
            if params['optimized_search']:  # use optimized search model if available
                [probs, prev_out, alphas] = self.predict_cond_optimized(X, state_below, params, ii, prev_out)
            else:
                probs = self.predict_cond(X, state_below, params, ii)
            # total score for every sample is sum of -log of word prb
            score -= np.log(probs[0, int(Y[ii])])
            state_below = np.asarray([Y[:ii]], dtype='int64')
            # we must include an additional dimension if the input for each timestep are all the generated words so far
            if pad_on_batch:
                state_below = np.hstack((np.zeros((state_below.shape[0], 1), dtype='int64') + null_sym, state_below))
                if params['words_so_far']:
                    state_below = np.expand_dims(state_below, axis=0)
            else:
                state_below = np.hstack((np.zeros((state_below.shape[0], 1), dtype='int64'), state_below,
                                         np.zeros((state_below.shape[0],
                                                   max(params['maxlen'] - state_below.shape[1] - 1, 0)),
                                                  dtype='int64')))

                if params['words_so_far']:
                    state_below = np.expand_dims(state_below, axis=0)
                    state_below = np.hstack((state_below,
                                             np.zeros((state_below.shape[0], params['maxlen'] - state_below.shape[1],
                                                       state_below.shape[2]))))


            if params['optimized_search'] and ii > 0:
                # filter next search inputs w.r.t. remaining samples
                for idx_vars in range(len(prev_out)):
                    prev_out[idx_vars] = prev_out[idx_vars]

        return score

    def scoreNet(self):
        """
        Approximates by beam search the best predictions of the net on the dataset splits chosen.
        Params from config that affect the sarch process:
            * batch_size: size of the batch
            * n_parallel_loaders: number of parallel data batch loaders
            * normalization: apply data normalization on images/features or not (only if using images/features as input)
            * mean_substraction: apply mean data normalization on images or not (only if using images as input)
            * predict_on_sets: list of set splits for which we want to extract the predictions ['train', 'val', 'test']
            * optimized_search: boolean indicating if the used model has the optimized Beam Search implemented
             (separate self.model_init and self.model_next models for reusing the information from previous timesteps).

        The following attributes must be inserted to the model when building an optimized search model:

            * ids_inputs_init: list of input variables to model_init (must match inputs to conventional model)
            * ids_outputs_init: list of output variables of model_init (model probs must be the first output)
            * ids_inputs_next: list of input variables to model_next (previous word must be the first input)
            * ids_outputs_next: list of output variables of model_next (model probs must be the first output and
                                the number of out variables must match the number of in variables)
            * matchings_init_to_next: dictionary from 'ids_outputs_init' to 'ids_inputs_next'
            * matchings_next_to_next: dictionary from 'ids_outputs_next' to 'ids_inputs_next'

        :returns predictions: dictionary with set splits as keys and matrices of predictions as values.
        """

        # Check input parameters and recover default values if needed
        default_params = {'batch_size': 50, 'n_parallel_loaders': 8, 'beam_size': 5,
                          'normalize': False, 'mean_substraction': True,
                          'predict_on_sets': ['val'], 'maxlen': 20, 'n_samples': -1,
                          'model_inputs': ['source_text', 'state_below'],
                          'model_outputs': ['description'],
                          'dataset_inputs': ['source_text', 'state_below'],
                          'dataset_outputs': ['description'],
                          'alpha_factor': 1.0,
                          'sampling_type': 'max_likelihood',
                          'words_so_far': False,
                          'optimized_search': False,
                          'state_below_index': -1,
                          'output_text_index': 0,
                          'pos_unk': False,
                          'heuristic': 0,
                          'mapping': None
                          }
        params = self.checkParameters(self.params, default_params)

        scores_dict = dict()

        for s in params['predict_on_sets']:
            logging.info("<<< Scoring outputs of " + s + " set >>>")
            assert len(params['model_inputs']) > 0, 'We need at least one input!'
            if not params['optimized_search']:  # use optimized search model if available
                assert not params['pos_unk'], 'PosUnk is not supported with non-optimized beam search methods'
            params['pad_on_batch'] = self.dataset.pad_on_batch[params['dataset_inputs'][-1]]
            # Calculate how many interations are we going to perform
            n_samples = eval("self.dataset.len_" + s)
            num_iterations = int(math.ceil(float(n_samples) / params['batch_size']))

            # Prepare data generator: We won't use an Homogeneous_Data_Batch_Generator here
            # TODO: We prepare data as model 0... Different data preparators for each model?
            data_gen = Data_Batch_Generator(s,
                                            self.models[0],
                                            self.dataset,
                                            num_iterations,
                                            shuffle=False,
                                            batch_size=params['batch_size'],
                                            normalization=params['normalize'],
                                            data_augmentation=False,
                                            mean_substraction=params['mean_substraction'],
                                            predict=False).generator()
            sources_sampling = []
            scores = []
            total_cost = 0
            sampled = 0
            start_time = time.time()
            eta = -1
            for j in range(num_iterations):
                data = data_gen.next()
                X = dict()
                s_dict = {}
                for input_id in params['model_inputs']:
                    X[input_id] = data[0][input_id]
                    s_dict[input_id] = X[input_id]
                sources_sampling.append(s_dict)

                Y = dict()
                for output_id in params['model_outputs']:
                    Y[output_id] = data[1][output_id]

                for i in range(len(X[params['model_inputs'][0]])):
                    sampled += 1
                    sys.stdout.write('\r')
                    sys.stdout.write("Scored %d/%d  -  ETA: %ds " % (sampled, n_samples, int(eta)))
                    sys.stdout.flush()
                    x = dict()
                    y = dict()

                    for input_id in params['model_inputs']:
                        x[input_id] = np.asarray([X[input_id][i]])
                    y = self.models[0].one_hot_2_indices([Y[params['dataset_outputs'][params['output_text_index']]][i]],
                                                         pad_sequences=True, verbose=0)[0]
                    score = self.score_cond_model(x, y, params, null_sym=self.dataset.extra_words['<null>'])
                    if params['normalize']:
                        counts = float(len(y) ** params['alpha_factor'])
                        score /= counts
                    scores.append(score)
                    total_cost += score
                    eta = (n_samples - sampled) * (time.time() - start_time) / sampled

            sys.stdout.write('Total cost of the translations: %f \t '
                             'Average cost of the translations: %f\n' % (total_cost, total_cost / n_samples))
            sys.stdout.write('The scoring took: %f secs (Speed: %f sec/sample)\n' %
                             ((time.time() - start_time), (time.time() - start_time) / n_samples))

            sys.stdout.flush()
            scores_dict[s] = scores
        return scores_dict

    # ------------------------------------------------------- #
    #       DECODING FUNCTIONS
    #           Functions for decoding predictions
    # ------------------------------------------------------- #

    def sample(self, a, temperature=1.0):
        """
        Helper function to sample an index from a probability array
        :param a: Probability array
        :param temperature: The higher, the flatter probabilities. Hence more random outputs.
        :return:
        """
        a = np.log(a) / temperature
        a = np.exp(a) / np.sum(np.exp(a))
        return np.argmax(np.random.multinomial(1, a, 1))

    def sampling(self, scores, sampling_type='max_likelihood', temperature=1.0):
        """
        Sampling words (each sample is drawn from a categorical distribution).
        Or picks up words that maximize the likelihood.
        :param scores: array of size #samples x #classes;
        every entry determines a score for sample i having class j
        :param sampling_type:
        :param temperature: Temperature for the predictions. The higher, the flatter probabilities. Hence more random outputs.
        :return: set of indices chosen as output, a vector of size #samples
        """
        if isinstance(scores, dict):
            scores = scores['output']

        if sampling_type == 'multinomial':
            preds = np.asarray(scores).astype('float64')
            preds = np.log(preds) / temperature
            exp_preds = np.exp(preds)
            preds = exp_preds / np.sum(exp_preds)
            probas = np.random.multinomial(1, preds, 1)
            return np.argmax(probas)
        elif sampling_type == 'max_likelihood':
            return np.argmax(scores, axis=-1)
        else:
            raise NotImplementedError()

    def decode_predictions(self, preds, temperature, index2word, sampling_type, verbose=0):
        """
        Decodes predictions
        :param preds: Predictions codified as the output of a softmax activation function.
        :param temperature: Temperature for sampling.
        :param index2word: Mapping from word indices into word characters.
        :param sampling_type: 'max_likelihood' or 'multinomial'.
        :param verbose: Verbosity level, by default 0.
        :return: List of decoded predictions.
        """

        if verbose > 0:
            logging.info('Decoding prediction ...')
        flattened_preds = preds.reshape(-1, preds.shape[-1])
        flattened_answer_pred = map(lambda x: index2word[x],
                                    self.sampling(scores=flattened_preds,
                                                  sampling_type=sampling_type,
                                                  temperature=temperature))
        answer_pred_matrix = np.asarray(flattened_answer_pred).reshape(preds.shape[:2])
        answer_pred = []
        EOS = '<eos>'
        PAD = '<pad>'

        for a_no in answer_pred_matrix:
            init_token_pos = 0
            end_token_pos = [j for j, x in enumerate(a_no) if x == EOS or x == PAD]
            end_token_pos = None if len(end_token_pos) == 0 else end_token_pos[0]
            tmp = ' '.join(a_no[init_token_pos:end_token_pos])
            answer_pred.append(tmp)
        return answer_pred

    def replace_unknown_words(self, src_word_seq, trg_word_seq, hard_alignment, unk_symbol,
                              heuristic=0, mapping=None, verbose=0):
        """
        Replaces unknown words from the target sentence according to some heuristic.
        Borrowed from: https://github.com/sebastien-j/LV_groundhog/blob/master/experiments/nmt/replace_UNK.py
        :param src_word_seq: Source sentence words
        :param trg_word_seq: Hypothesis words
        :param hard_alignment: Target-Source alignments
        :param unk_symbol: Symbol in trg_word_seq to replace
        :param heuristic: Heuristic (0, 1, 2)
        :param mapping: External alignment dictionary
        :param verbose: Verbosity level
        :return: trg_word_seq with replaced unknown words
        """
        trans_words = trg_word_seq
        new_trans_words = []
        if verbose > 2:
            print "Input sentence:", src_word_seq
            print "Hard alignments", hard_alignment
        for j in xrange(len(trans_words)):
            if trans_words[j] == unk_symbol:
                UNK_src = src_word_seq[hard_alignment[j]]
                if heuristic == 0:  # Copy (ok when training with large vocabularies on en->fr, en->de)
                    new_trans_words.append(UNK_src)
                elif heuristic == 1:
                    # Use the most likely translation (with t-table). If not found, copy the source word.
                    # Ok for small vocabulary (~30k) models
                    if mapping.get(UNK_src) is not None:
                        new_trans_words.append(mapping[UNK_src])
                    else:
                        new_trans_words.append(UNK_src)
                elif heuristic == 2:
                    # Use t-table if the source word starts with a lowercase letter. Otherwise copy
                    # Sometimes works better than other heuristics
                    if mapping.get(UNK_src) is not None and UNK_src.decode('utf-8')[0].islower():
                        new_trans_words.append(mapping[UNK_src])
                    else:
                        new_trans_words.append(UNK_src)
            else:
                new_trans_words.append(trans_words[j])

        return new_trans_words

    def decode_predictions_beam_search(self, preds, index2word, alphas=None, heuristic=0,
                                       x_text=None, unk_symbol='<unk>', pad_sequences=False,
                                       mapping=None, verbose=0):
        """
        Decodes predictions from the BeamSearch method.
        :param preds: Predictions codified as word indices.
        :param index2word: Mapping from word indices into word characters.
        :param pad_sequences: Whether we should make a zero-pad on the input sequence.
        :param verbose: Verbosity level, by default 0.
        :return: List of decoded predictions
        """
        if verbose > 0:
            logging.info('Decoding beam search prediction ...')

        if alphas is not None:
            assert x_text is not None, 'When using POS_UNK, you must provide the input ' \
                                       'text to decode_predictions_beam_search!'
            if verbose > 0:
                logging.info('Using heuristic %d' % heuristic)
        if pad_sequences:
            preds = [pred[:sum([int(elem > 0) for elem in pred]) + 1] for pred in preds]
        flattened_answer_pred = [map(lambda x: index2word[x], pred) for pred in preds]
        answer_pred = []

        if alphas is not None:
            x_text = map(lambda x: x.split(), x_text)
            hard_alignments = map(
                lambda alignment, x_sentence: np.argmax(alignment[:, :max(1, len(x_sentence))], axis=1),
                alphas, x_text)
            for i, a_no in enumerate(flattened_answer_pred):
                if unk_symbol in a_no:
                    if verbose > 1:
                        print unk_symbol, "at sentence number", i
                        print "hypothesis:", a_no
                        if verbose > 2:
                            print "alphas:", alphas[i]

                    a_no = self.replace_unknown_words(x_text[i],
                                                      a_no,
                                                      hard_alignments[i],
                                                      unk_symbol,
                                                      heuristic=heuristic,
                                                      mapping=mapping,
                                                      verbose=verbose)
                    if verbose > 1:
                        print "After unk_replace:", a_no
                tmp = ' '.join(a_no[:-1])
                answer_pred.append(tmp)
        else:
            for a_no in flattened_answer_pred:
                tmp = ' '.join(a_no[:-1])
                answer_pred.append(tmp)
        return answer_pred


    def one_hot_2_indices(self, preds, pad_sequences=True, verbose=0):
        """
        Converts a one-hot codification into a index-based one
        :param preds: Predictions codified as one-hot vectors.
        :param verbose: Verbosity level, by default 0.
        :return: List of convertedpredictions
        """
        if verbose > 0:
            logging.info('Converting one hot prediction into indices...')
        preds = map(lambda x: np.nonzero(x)[1], preds)
        if pad_sequences:
            preds = [pred[:sum([int(elem > 0) for elem in pred]) + 1] for pred in preds]
        return preds


    def decode_predictions_one_hot(self, preds, index2word, verbose=0):
        """
        Decodes predictions following a one-hot codification.
        :param preds: Predictions codified as one-hot vectors.
        :param index2word: Mapping from word indices into word characters.
        :param verbose: Verbosity level, by default 0.
        :return: List of decoded predictions
        """
        if verbose > 0:
            logging.info('Decoding one hot prediction ...')
        preds = map(lambda x: np.nonzero(x)[1], preds)
        PAD = '<pad>'
        flattened_answer_pred = [map(lambda x: index2word[x], pred) for pred in preds]
        answer_pred_matrix = np.asarray(flattened_answer_pred)
        answer_pred = []

        for a_no in answer_pred_matrix:
            end_token_pos = [j for j, x in enumerate(a_no) if x == PAD]
            end_token_pos = None if len(end_token_pos) == 0 else end_token_pos[0]
            tmp = ' '.join(a_no[:end_token_pos])
            answer_pred.append(tmp)
        return answer_pred

    def prepareData(self, X_batch, Y_batch=None):
        """
        Prepares the data for the model, depending on its type (Sequential, Model, Graph).
        :param X_batch: Batch of input data.
        :param Y_batch: Batch output data.
        :return: Prepared data.
        """
        if isinstance(self.model, Sequential):
            data = self._prepareSequentialData(X_batch, Y_batch)
        elif isinstance(self.model, Model):
            data = self._prepareModelData(X_batch, Y_batch)
        else:
            raise NotImplementedError
        return data

    def _prepareSequentialData(self, X, Y=None, sample_weights=False):

        # Format input data
        if len(self.inputsMapping.keys()) == 1:  # single input
            X = X[self.inputsMapping[0]]
        else:
            X_new = [0 for i in range(len(self.inputsMapping.keys()))]  # multiple inputs
            for in_model, in_ds in self.inputsMapping.iteritems():
                X_new[in_model] = X[in_ds]
            X = X_new

        # Format output data (only one output possible for Sequential models)
        Y_sample_weights = None
        if Y is not None:
            if len(self.outputsMapping.keys()) == 1:  # single output
                if isinstance(Y[self.outputsMapping[0]], tuple):
                    Y = Y[self.outputsMapping[0]][0]
                    Y_sample_weights = Y[self.outputsMapping[0]][1]
                else:
                    Y = Y[self.outputsMapping[0]]
            else:
                Y_new = [0 for i in range(len(self.outputsMapping.keys()))]  # multiple outputs
                Y_sample_weights = [None for i in range(len(self.outputsMapping.keys()))]
                for out_model, out_ds in self.outputsMapping.iteritems():
                    if isinstance(Y[out_ds], tuple):
                        Y_new[out_model] = Y[out_ds][0]
                        Y_sample_weights[out_model] = Y[out_ds][1]
                    else:
                        Y_new[out_model] = Y[out_ds]
                Y = Y_new

        return [X, Y] if Y_sample_weights is None else [X, Y, Y_sample_weights]

    def _prepareModelData(self, X, Y=None):
        X_new = dict()
        Y_new = dict()
        Y_sample_weights = dict()

        # Format input data
        for in_model, in_ds in self.inputsMapping.iteritems():
            X_new[in_model] = X[in_ds]

        # Format output data
        if Y is not None:
            for out_model, out_ds in self.outputsMapping.iteritems():
                if isinstance(Y[out_ds], tuple):
                    Y_new[out_model] = Y[out_ds][0]
                    Y_sample_weights[out_model] = Y[out_ds][1]
                else:
                    Y_new[out_model] = Y[out_ds]

        return [X_new, Y_new] if Y_sample_weights == dict() else [X_new, Y_new, Y_sample_weights]

    def _prepareGraphData(self, X, Y=None):

        data = dict()
        data_sample_weight = dict()
        any_sample_weight = False
        last_out = self.acc_output

        # Format input data
        for in_model, in_ds in self.inputsMapping.iteritems():
            data[in_model] = X[in_ds]

        # Format output data
        for out_model, out_ds in self.outputsMapping.iteritems():
            if Y is None:
                data[out_model] = None
            else:
                if isinstance(Y[out_ds], tuple):
                    data[out_model] = Y[out_ds][0]
                    data_sample_weight[out_model] = Y[out_ds][1]
                    any_sample_weight = True
                else:
                    data[out_model] = Y[out_ds]

        return [(data, data_sample_weight), last_out] if any_sample_weight else [data, last_out]

    def _getGraphAccuracy(self, data, prediction, topN=5):
        """
            Calculates the accuracy obtained from a set of samples on a Graph model.
        """

        accuracies = dict()
        top_accuracies = dict()
        for key, val in prediction.iteritems():
            pred = np_utils.categorical_probas_to_classes(val)
            top_pred = np.argsort(val, axis=1)[:, ::-1][:, :np.min([topN, val.shape[1]])]
            GT = np_utils.categorical_probas_to_classes(data[key])

            # Top1 accuracy
            correct = [1 if pred[i] == GT[i] else 0 for i in range(len(pred))]
            accuracies[key] = float(np.sum(correct)) / float(len(correct))

            # TopN accuracy
            top_correct = [1 if GT[i] in top_pred[i, :] else 0 for i in range(top_pred.shape[0])]
            top_accuracies[key] = float(np.sum(top_correct)) / float(len(top_correct))

        return [accuracies, top_accuracies]

    def _getSequentialAccuracy(self, GT, pred, topN=5):
        """
            Calculates the topN accuracy obtained from a set of samples on a Sequential model.
        """
        top_pred = np.argsort(pred, axis=1)[:, ::-1][:, :np.min([topN, pred.shape[1]])]
        pred = np_utils.categorical_probas_to_classes(pred)
        GT = np_utils.categorical_probas_to_classes(GT)

        # Top1 accuracy
        correct = [1 if pred[i] == GT[i] else 0 for i in range(len(pred))]
        accuracies = float(np.sum(correct)) / float(len(correct))

        # TopN accuracy
        top_correct = [1 if GT[i] in top_pred[i, :] else 0 for i in range(top_pred.shape[0])]
        top_accuracies = float(np.sum(top_correct)) / float(len(top_correct))

        return [accuracies, top_accuracies]

    # ------------------------------------------------------- #
    #       VISUALIZATION
    #           Methods for train logging and visualization
    # ------------------------------------------------------- #

    def __str__(self):
        """
        Plot basic model information.
        """

        # if(isinstance(self.model, Model)):
        print_summary(self.model.layers)
        return ''

        obj_str = '-----------------------------------------------------------------------------------\n'
        class_name = self.__class__.__name__
        obj_str += '\t\t' + class_name + ' instance\n'
        obj_str += '-----------------------------------------------------------------------------------\n'

        # Print pickled attributes
        for att in self.__toprint:
            obj_str += att + ': ' + str(self.__dict__[att])
            obj_str += '\n'

        # Print layers structure
        obj_str += "\n::: Layers structure:\n\n"
        obj_str += 'MODEL TYPE: ' + self.model.__class__.__name__ + '\n'
        if isinstance(self.model, Sequential):
            obj_str += "INPUT: " + str(tuple(self.model.layers[0].input_shape)) + "\n"
            for i, layer in enumerate(self.model.layers):
                obj_str += str(layer.name) + ' ' + str(layer.output_shape) + '\n'
            obj_str += "OUTPUT: " + str(self.model.layers[-1].output_shape) + "\n"
        else:
            for i, inputs in enumerate(self.model.input_config):
                obj_str += "INPUT (" + str(i) + "): " + str(inputs['name']) + ' ' + str(
                    tuple(inputs['input_shape'])) + "\n"
            for node in self.model.node_config:
                obj_str += str(node['name']) + ', in [' + str(node['input']) + ']' + ', out_shape: ' + str(
                    self.model.nodes[node['name']].output_shape) + '\n'
            for i, outputs in enumerate(self.model.output_config):
                obj_str += "OUTPUT (" + str(i) + "): " + str(outputs['name']) + ', in [' + str(
                    outputs['input']) + ']' + ', out_shape: ' + str(
                    self.model.outputs[outputs['name']].output_shape) + "\n"

        obj_str += '-----------------------------------------------------------------------------------\n'

        print_summary(self.model.layers)

        return obj_str

    def log(self, mode, data_type, value):
        """
        Stores the train and val information for plotting the training progress.

        :param mode: 'train', 'val' or 'test'
        :param data_type: 'iteration', 'loss', 'accuracy', etc.
        :param value: numerical value taken by the data_type
        """
        if mode not in self.__modes:
            raise Exception('The provided mode "' + mode + '" is not valid.')
        # if data_type not in self.__data_types:
        #    raise Exception('The provided data_type "'+ data_type +'" is not valid.')

        if mode not in self.__logger:
            self.__logger[mode] = dict()
        if data_type not in self.__logger[mode]:
            self.__logger[mode][data_type] = list()
        self.__logger[mode][data_type].append(value)

    def getLog(self, mode, data_type):
        """
        Returns the all logged values for a given mode and a given data_type

        :param mode: 'train', 'val' or 'test'
        :param data_type: 'iteration', 'loss', 'accuracy', etc.
        :return: list of values logged
        """
        if mode not in self.__logger:
            return [None]
        elif data_type not in self.__logger[mode]:
            return [None]
        else:
            return self.__logger[mode][data_type]

    def plot(self):
        """
            Plots the training progress information.
        """
        colours = {'train_accuracy_top-5': 'y', 'train_accuracy': 'y', 'train_loss': 'k',
                   'val_accuracy_top-5': 'g', 'val_accuracy': 'g', 'val_loss': 'b',
                   'max_accuracy': 'r'}

        plt.figure(1)

        all_iterations = []
        # Plot train information
        if 'train' in self.__logger:
            if 'iteration' not in self.__logger['train']:
                raise Exception("The training 'iteration' must be logged into the model for plotting.")
            if 'accuracy' not in self.__logger['train'] and 'loss' not in self.__logger['train']:
                raise Exception("Either train 'accuracy' and/or 'loss' must be logged into the model for plotting.")

            iterations = self.__logger['train']['iteration']
            all_iterations = all_iterations + iterations

            # Loss
            if 'loss' in self.__logger['train']:
                loss = self.__logger['train']['loss']
                plt.subplot(211)
                # plt.plot(iterations, loss, colours['train_loss']+'o')
                plt.plot(iterations, loss, colours['train_loss'])
                plt.subplot(212)
                plt.plot(iterations, loss, colours['train_loss'])

            # Accuracy
            if 'accuracy' in self.__logger['train']:
                accuracy = self.__logger['train']['accuracy']
                plt.subplot(211)
                plt.plot(iterations, accuracy, colours['train_accuracy'] + 'o')
                plt.plot(iterations, accuracy, colours['train_accuracy'])
                plt.subplot(212)
                plt.plot(iterations, accuracy, colours['train_accuracy'] + 'o')
                plt.plot(iterations, accuracy, colours['train_accuracy'])

            # Accuracy Top-5
            if 'accuracy top-5' in self.__logger['train']:
                accuracy = self.__logger['train']['accuracy top-5']
                plt.subplot(211)
                plt.plot(iterations, accuracy, colours['train_accuracy_top-5'] + '.')
                plt.plot(iterations, accuracy, colours['train_accuracy_top-5'])
                plt.subplot(212)
                plt.plot(iterations, accuracy, colours['train_accuracy_top-5'] + '.')
                plt.plot(iterations, accuracy, colours['train_accuracy_top-5'])

        # Plot val information
        if 'val' in self.__logger:
            if 'iteration' not in self.__logger['val']:
                raise Exception("The validation 'iteration' must be logged into the model for plotting.")
            if 'accuracy' not in self.__logger['val'] and 'loss' not in self.__logger['train']:
                raise Exception("Either val 'accuracy' and/or 'loss' must be logged into the model for plotting.")

            iterations = self.__logger['val']['iteration']
            all_iterations = all_iterations + iterations

            # Loss
            if 'loss' in self.__logger['val']:
                loss = self.__logger['val']['loss']
                plt.subplot(211)
                # plt.plot(iterations, loss, colours['val_loss']+'o')
                plt.plot(iterations, loss, colours['val_loss'])
                plt.subplot(212)
                plt.plot(iterations, loss, colours['val_loss'])

            # Accuracy
            if 'accuracy' in self.__logger['val']:
                accuracy = self.__logger['val']['accuracy']
                plt.subplot(211)
                plt.plot(iterations, accuracy, colours['val_accuracy'] + 'o')
                plt.plot(iterations, accuracy, colours['val_accuracy'])
                plt.subplot(212)
                plt.plot(iterations, accuracy, colours['val_accuracy'] + 'o')
                plt.plot(iterations, accuracy, colours['val_accuracy'])

            # Accuracy Top-5
            if 'accuracy top-5' in self.__logger['val']:
                accuracy = self.__logger['val']['accuracy top-5']
                plt.subplot(211)
                plt.plot(iterations, accuracy, colours['val_accuracy_top-5'] + '.')
                plt.plot(iterations, accuracy, colours['val_accuracy_top-5'])
                plt.subplot(212)
                plt.plot(iterations, accuracy, colours['val_accuracy_top-5'] + '.')
                plt.plot(iterations, accuracy, colours['val_accuracy_top-5'])

        # Plot max accuracy
        max_iter = np.max(all_iterations + [0])
        plt.subplot(211)
        plt.plot([0, max_iter], [1, 1], colours['max_accuracy'] + '-')
        plt.subplot(212)
        plt.plot([0, max_iter], [1, 1], colours['max_accuracy'] + '-')
        plt.axis([0, max_iter, 0, 1])  # limit height to 1

        # Fill labels
        # plt.ylabel('Loss/Accuracy')
        plt.xlabel('Iteration')
        plt.subplot(211)
        plt.title('Training progress')

        # Create plots dir
        if not os.path.isdir(self.plot_path):
            os.makedirs(self.plot_path)

        # Save figure
        plot_file = self.plot_path + '/iter_' + str(max_iter) + '.jpg'
        plt.savefig(plot_file)
        if not self.silence:
            logging.info("Progress plot saved in " + plot_file)

        # Close plot window
        plt.close()

    # ------------------------------------------------------- #
    #   MODELS
    #       Available definitions of CNN models (see basic_model as an example)
    #       All the models must include the following parameters:
    #           nOutput, input
    # ------------------------------------------------------- #

    def basic_model(self, nOutput, input):
        """
            Builds a basic CNN model.
        """

        # Define inputs and outputs IDs
        self.ids_inputs = ['input']
        self.ids_outputs = ['output']

        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        inp = Input(shape=input_shape, name='input')

        # input: 100x100 images with 3 channels -> (3, 100, 100) tensors.
        # this applies 32 convolution filters of size 3x3 each.
        x = Convolution2D(32, 3, 3, border_mode='valid')(inp)
        x = Activation('relu')(x)
        x = Convolution2D(32, 3, 3)(x)
        x = Activation('relu')(x)
        x = MaxPooling2D(pool_size=(2, 2))(x)
        x = Dropout(0.25)(x)

        x = Convolution2D(64, 3, 3, border_mode='valid')(x)
        x = Activation('relu')(x)
        x = Convolution2D(64, 3, 3)(x)
        x = Activation('relu')(x)
        x = MaxPooling2D(pool_size=(2, 2))(x)
        x = Dropout(0.25)(x)

        x = Convolution2D(128, 3, 3, border_mode='valid')(x)
        x = Activation('relu')(x)
        x = Convolution2D(64, 3, 3)(x)
        x = Activation('relu')(x)
        x = MaxPooling2D(pool_size=(2, 2))(x)
        x = Dropout(0.25)(x)

        x = Convolution2D(256, 3, 3, border_mode='valid')(x)
        x = Activation('relu')(x)
        x = Convolution2D(64, 3, 3)(x)
        x = Activation('relu')(x)
        x = MaxPooling2D(pool_size=(2, 2))(x)
        x = Dropout(0.25)(x)

        x = Convolution2D(256, 3, 3, border_mode='valid')(x)
        x = Activation('relu')(x)
        x = Convolution2D(64, 3, 3)(x)
        x = Activation('relu')(x)
        x = MaxPooling2D(pool_size=(2, 2))(x)
        x = Dropout(0.25)(x)

        x = Flatten()(x)
        # Note: Keras does automatic shape inference.
        x = Dense(1024)(x)
        x = Activation('relu')(x)
        x = Dropout(0.5)(x)

        x = Dense(nOutput)(x)
        out = Activation('softmax', name='output')(x)

        self.model = Model(input=inp, output=out)

    def basic_model_seq(self, nOutput, input):
        """
            Builds a basic CNN model.
        """

        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Sequential()
        # input: 100x100 images with 3 channels -> (3, 100, 100) tensors.
        # this applies 32 convolution filters of size 3x3 each.
        self.model.add(Convolution2D(32, 3, 3, border_mode='valid', input_shape=input_shape))
        self.model.add(Activation('relu'))
        self.model.add(Convolution2D(32, 3, 3))
        self.model.add(Activation('relu'))
        self.model.add(MaxPooling2D(pool_size=(2, 2)))
        self.model.add(Dropout(0.25))

        self.model.add(Convolution2D(64, 3, 3, border_mode='valid'))
        self.model.add(Activation('relu'))
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(Activation('relu'))
        self.model.add(MaxPooling2D(pool_size=(2, 2)))
        self.model.add(Dropout(0.25))

        self.model.add(Convolution2D(128, 3, 3, border_mode='valid'))
        self.model.add(Activation('relu'))
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(Activation('relu'))
        self.model.add(MaxPooling2D(pool_size=(2, 2)))
        self.model.add(Dropout(0.25))

        self.model.add(Convolution2D(256, 3, 3, border_mode='valid'))
        self.model.add(Activation('relu'))
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(Activation('relu'))
        self.model.add(MaxPooling2D(pool_size=(2, 2)))
        self.model.add(Dropout(0.25))

        self.model.add(Convolution2D(256, 3, 3, border_mode='valid'))
        self.model.add(Activation('relu'))
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(Activation('relu'))
        self.model.add(MaxPooling2D(pool_size=(2, 2)))
        self.model.add(Dropout(0.25))

        self.model.add(Flatten())
        # Note: Keras does automatic shape inference.
        self.model.add(Dense(1024))
        self.model.add(Activation('relu'))
        self.model.add(Dropout(0.5))

        self.model.add(Dense(nOutput))
        self.model.add(Activation('softmax'))

    def One_vs_One(self, nOutput, input):
        """
            Builds a simple One_vs_One network with 3 convolutional layers (useful for ECOC models).
        """
        # default lr=0.1, momentum=0.
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Sequential()
        self.model.add(ZeroPadding2D((1, 1), input_shape=input_shape))  # default input_shape=(3,224,224)
        self.model.add(Convolution2D(32, 1, 1, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(16, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(8, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(1, 1)))

        self.model.add(Flatten())
        self.model.add(Dropout(0.5))
        self.model.add(Dense(nOutput, activation='softmax'))  # default nOutput=1000

    def VGG_16(self, nOutput, input):
        """
            Builds a VGG model with 16 layers.
        """
        # default lr=0.1, momentum=0.
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Sequential()
        self.model.add(ZeroPadding2D((1, 1), input_shape=input_shape))  # default input_shape=(3,224,224)
        self.model.add(Convolution2D(64, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(64, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(128, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(128, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3, activation='relu'))
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(Flatten())
        self.model.add(Dense(4096, activation='relu'))
        self.model.add(Dropout(0.5))
        self.model.add(Dense(4096, activation='relu'))
        self.model.add(Dropout(0.5))
        self.model.add(Dense(nOutput, activation='softmax'))  # default nOutput=1000

    def VGG_16_PReLU(self, nOutput, input):
        """
            Builds a VGG model with 16 layers and with PReLU activations.
        """

        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Sequential()
        self.model.add(ZeroPadding2D((1, 1), input_shape=input_shape))  # default input_shape=(3,224,224)
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(64, 3, 3))
        self.model.add(PReLU())
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(128, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(128, 3, 3))
        self.model.add(PReLU())
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(256, 3, 3))
        self.model.add(PReLU())
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(ZeroPadding2D((1, 1)))
        self.model.add(Convolution2D(512, 3, 3))
        self.model.add(PReLU())
        self.model.add(MaxPooling2D((2, 2), strides=(2, 2)))

        self.model.add(Flatten())
        self.model.add(Dense(4096))
        self.model.add(PReLU())
        self.model.add(Dropout(0.5))
        self.model.add(Dense(4096))
        self.model.add(PReLU())
        self.model.add(Dropout(0.5))
        self.model.add(Dense(nOutput, activation='softmax'))  # default nOutput=1000

    def VGG_16_FunctionalAPI(self, nOutput, input):
        """
            16-layered VGG model implemented in Keras' Functional API
        """
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        vis_input = Input(shape=input_shape, name="vis_input")

        x = ZeroPadding2D((1, 1))(vis_input)
        x = Convolution2D(64, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(64, 3, 3, activation='relu')(x)
        x = MaxPooling2D((2, 2), strides=(2, 2))(x)

        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(128, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(128, 3, 3, activation='relu')(x)
        x = MaxPooling2D((2, 2), strides=(2, 2))(x)

        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(256, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(256, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(256, 3, 3, activation='relu')(x)
        x = MaxPooling2D((2, 2), strides=(2, 2))(x)

        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = MaxPooling2D((2, 2), strides=(2, 2))(x)

        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = ZeroPadding2D((1, 1))(x)
        x = Convolution2D(512, 3, 3, activation='relu')(x)
        x = MaxPooling2D((2, 2), strides=(2, 2),
                         name='last_max_pool')(x)

        x = Flatten()(x)
        x = Dense(4096, activation='relu')(x)
        x = Dropout(0.5)(x)
        x = Dense(4096, activation='relu')(x)
        x = Dropout(0.5, name='last_dropout')(x)
        x = Dense(nOutput, activation='softmax', name='output')(x)  # nOutput=1000 by default

        self.model = Model(input=vis_input, output=x)

    def VGG_19(self, nOutput, input):

        # Define inputs and outputs IDs
        self.ids_inputs = ['input_1']
        self.ids_outputs = ['predictions']

        # Load VGG19 model pre-trained on ImageNet
        self.model = VGG19()

        # Recover input layer
        image = self.model.get_layer(self.ids_inputs[0]).output

        # Recover last layer kept from original model
        out = self.model.get_layer('fc2').output
        out = Dense(nOutput, name=self.ids_outputs[0], activation='softmax')(out)

        self.model = Model(input=image, output=out)

    def VGG_19_ImageNet(self, nOutput, input):

        # Define inputs and outputs IDs
        self.ids_inputs = ['input_1']
        self.ids_outputs = ['predictions']

        # Load VGG19 model pre-trained on ImageNet
        self.model = VGG19(weights='imagenet', layers_lr=0.001)

        # Recover input layer
        image = self.model.get_layer(self.ids_inputs[0]).output

        # Recover last layer kept from original model
        out = self.model.get_layer('fc2').output
        out = Dense(nOutput, name=self.ids_outputs[0], activation='softmax')(out)

        self.model = Model(input=image, output=out)

    ########################################
    # GoogLeNet implementation from http://dandxy89.github.io/ImageModels/googlenet/
    ########################################

    def inception_module(self, x, params, dim_ordering, concat_axis,
                         subsample=(1, 1), activation='relu',
                         border_mode='same', weight_decay=None):

        # https://gist.github.com/nervanazoo/2e5be01095e935e90dd8  #
        # file-googlenet_neon-py

        (branch1, branch2, branch3, branch4) = params

        if weight_decay:
            W_regularizer = l2(weight_decay)
            b_regularizer = l2(weight_decay)
        else:
            W_regularizer = None
            b_regularizer = None

        pathway1 = Convolution2D(branch1[0], 1, 1,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(x)

        pathway2 = Convolution2D(branch2[0], 1, 1,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(x)
        pathway2 = Convolution2D(branch2[1], 3, 3,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(pathway2)

        pathway3 = Convolution2D(branch3[0], 1, 1,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(x)
        pathway3 = Convolution2D(branch3[1], 5, 5,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(pathway3)

        pathway4 = MaxPooling2D(pool_size=(1, 1), dim_ordering=dim_ordering)(x)
        pathway4 = Convolution2D(branch4[0], 1, 1,
                                 subsample=subsample,
                                 activation=activation,
                                 border_mode=border_mode,
                                 W_regularizer=W_regularizer,
                                 b_regularizer=b_regularizer,
                                 bias=False,
                                 dim_ordering=dim_ordering)(pathway4)

        return merge([pathway1, pathway2, pathway3, pathway4],
                     mode='concat', concat_axis=concat_axis)

    def conv_layer(self, x, nb_filter, nb_row, nb_col, dim_ordering,
                   subsample=(1, 1), activation='relu',
                   border_mode='same', weight_decay=None, padding=None):

        if weight_decay:
            W_regularizer = l2(weight_decay)
            b_regularizer = l2(weight_decay)
        else:
            W_regularizer = None
            b_regularizer = None

        x = Convolution2D(nb_filter, nb_row, nb_col,
                          subsample=subsample,
                          activation=activation,
                          border_mode=border_mode,
                          W_regularizer=W_regularizer,
                          b_regularizer=b_regularizer,
                          bias=False,
                          dim_ordering=dim_ordering)(x)

        if padding:
            for i in range(padding):
                x = ZeroPadding2D(padding=(1, 1), dim_ordering=dim_ordering)(x)

        return x

    def GoogLeNet_FunctionalAPI(self, nOutput, input):

        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        # Define image input layer
        img_input = Input(shape=input_shape, name='input_data')
        CONCAT_AXIS = 1
        NB_CLASS = nOutput  # number of classes (default 1000)
        DROPOUT = 0.4
        WEIGHT_DECAY = 0.0005  # L2 regularization factor
        USE_BN = True  # whether to use batch normalization
        # Theano - 'th' (channels, width, height)
        # Tensorflow - 'tf' (width, height, channels)
        DIM_ORDERING = 'th'
        pool_name = 'last_max_pool'  # name of the last max-pooling layer

        x = self.conv_layer(img_input, nb_col=7, nb_filter=64, subsample=(2, 2),
                            nb_row=7, dim_ordering=DIM_ORDERING, padding=1)
        x = MaxPooling2D(strides=(2, 2), pool_size=(3, 3), dim_ordering=DIM_ORDERING)(x)

        x = self.conv_layer(x, nb_col=1, nb_filter=64,
                            nb_row=1, dim_ordering=DIM_ORDERING)
        x = self.conv_layer(x, nb_col=3, nb_filter=192,
                            nb_row=3, dim_ordering=DIM_ORDERING, padding=1)
        x = MaxPooling2D(strides=(2, 2), pool_size=(3, 3), dim_ordering=DIM_ORDERING)(x)

        x = self.inception_module(x, params=[(64,), (96, 128), (16, 32), (32,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = self.inception_module(x, params=[(128,), (128, 192), (32, 96), (64,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)

        x = ZeroPadding2D(padding=(2, 2), dim_ordering=DIM_ORDERING)(x)
        x = MaxPooling2D(strides=(2, 2), pool_size=(3, 3), dim_ordering=DIM_ORDERING)(x)

        x = self.inception_module(x, params=[(192,), (96, 208), (16, 48), (64,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        # AUX 1 - Branch HERE
        x = self.inception_module(x, params=[(160,), (112, 224), (24, 64), (64,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = self.inception_module(x, params=[(128,), (128, 256), (24, 64), (64,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = self.inception_module(x, params=[(112,), (144, 288), (32, 64), (64,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        # AUX 2 - Branch HERE
        x = self.inception_module(x, params=[(256,), (160, 320), (32, 128), (128,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = MaxPooling2D(strides=(2, 2), pool_size=(3, 3), dim_ordering=DIM_ORDERING, name=pool_name)(x)

        x = self.inception_module(x, params=[(256,), (160, 320), (32, 128), (128,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = self.inception_module(x, params=[(384,), (192, 384), (48, 128), (128,)],
                                  dim_ordering=DIM_ORDERING, concat_axis=CONCAT_AXIS)
        x = AveragePooling2D(strides=(1, 1), dim_ordering=DIM_ORDERING)(x)
        x = Flatten()(x)
        x = Dropout(DROPOUT)(x)
        # x = Dense(output_dim=NB_CLASS,
        #          activation='linear')(x)
        x = Dense(output_dim=NB_CLASS,
                  activation='softmax', name='output')(x)

        self.model = Model(input=img_input, output=[x])

    ########################################

    def Identity_Layer(self, nOutput, input):
        """
            Builds an dummy Identity_Layer, which should give as output the same as the input.
            Only used for passing the output from a previous stage to the next (see Staged_Network).
        """
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Graph()
        # Input
        self.model.add_input(name='input', input_shape=input_shape)
        # Output
        self.model.add_output(name='output', input='input')

    def Union_Layer(self, nOutput, input):
        """
            Network with just a dropout and a softmax layers which is intended to serve as the final layer for an ECOC model
        """
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Sequential()
        self.model.add(Flatten(input_shape=input_shape))
        self.model.add(Dropout(0.5))
        self.model.add(Dense(nOutput, activation='softmax'))

    def One_vs_One_Inception(self, nOutput=2, input=[224, 224, 3]):
        """
            Builds a simple One_vs_One_Inception network with 2 inception layers (useful for ECOC models).
        """
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Graph()
        # Input
        self.model.add_input(name='input', input_shape=input_shape)
        # Inception Ea
        out_Ea = self.__addInception('inceptionEa', 'input', 4, 2, 8, 2, 2, 2)
        # Inception Eb
        out_Eb = self.__addInception('inceptionEb', out_Ea, 2, 2, 4, 2, 1, 1)
        # Average Pooling    pool_size=(7,7)
        self.model.add_node(AveragePooling2D(pool_size=input_shape[1:], strides=(1, 1)), name='ave_pool/ECOC',
                            input=out_Eb)
        # Softmax
        self.model.add_node(Flatten(), name='loss_OnevsOne/classifier_flatten', input='ave_pool/ECOC')
        self.model.add_node(Dropout(0.5), name='loss_OnevsOne/drop', input='loss_OnevsOne/classifier_flatten')
        self.model.add_node(Dense(nOutput, activation='softmax'), name='loss_OnevsOne', input='loss_OnevsOne/drop')
        # Output
        self.model.add_output(name='loss_OnevsOne/output', input='loss_OnevsOne')

    def add_One_vs_One_Inception(self, input, input_shape, id_branch, nOutput=2, activation='softmax'):
        """
            Builds a simple One_vs_One_Inception network with 2 inception layers on the top of the current model (useful for ECOC_loss models).
        """

        # Inception Ea
        out_Ea = self.__addInception('inceptionEa_' + str(id_branch), input, 4, 2, 8, 2, 2, 2)
        # Inception Eb
        out_Eb = self.__addInception('inceptionEb_' + str(id_branch), out_Ea, 2, 2, 4, 2, 1, 1)
        # Average Pooling    pool_size=(7,7)
        self.model.add_node(AveragePooling2D(pool_size=input_shape[1:], strides=(1, 1)),
                            name='ave_pool/ECOC_' + str(id_branch), input=out_Eb)
        # Softmax
        self.model.add_node(Flatten(),
                            name='fc_OnevsOne_' + str(id_branch) + '/flatten', input='ave_pool/ECOC_' + str(id_branch))
        self.model.add_node(Dropout(0.5),
                            name='fc_OnevsOne_' + str(id_branch) + '/drop',
                            input='fc_OnevsOne_' + str(id_branch) + '/flatten')
        output_name = 'fc_OnevsOne_' + str(id_branch)
        self.model.add_node(Dense(nOutput, activation=activation),
                            name=output_name, input='fc_OnevsOne_' + str(id_branch) + '/drop')

        return output_name

    def add_One_vs_One_Inception_Functional(self, input, input_shape, id_branch, nOutput=2, activation='softmax'):
        """
            Builds a simple One_vs_One_Inception network with 2 inception layers on the top of the current model (useful for ECOC_loss models).
        """

        in_node = self.model.get_layer(input).output

        # Inception Ea
        [out_Ea, out_Ea_name] = self.__addInception_Functional('inceptionEa_' + str(id_branch), in_node, 4, 2, 8, 2, 2,
                                                               2)
        # Inception Eb
        [out_Eb, out_Eb_name] = self.__addInception_Functional('inceptionEb_' + str(id_branch), out_Ea, 2, 2, 4, 2, 1,
                                                               1)
        # Average Pooling    pool_size=(7,7)
        x = AveragePooling2D(pool_size=input_shape, strides=(1, 1), name='ave_pool/ECOC_' + str(id_branch))(out_Eb)

        # Softmax
        output_name = 'fc_OnevsOne_' + str(id_branch)
        x = Flatten(name='fc_OnevsOne_' + str(id_branch) + '/flatten')(x)
        x = Dropout(0.5, name='fc_OnevsOne_' + str(id_branch) + '/drop')(x)
        out_node = Dense(nOutput, activation=activation, name=output_name)(x)

        return out_node

    def add_One_vs_One_3x3_Functional(self, input, input_shape, id_branch, nkernels, nOutput=2, activation='softmax'):

        # 3x3 convolution
        out_3x3 = Convolution2D(nkernels, 3, 3, name='3x3/ecoc_' + str(id_branch), activation='relu')(input)

        # Average Pooling    pool_size=(7,7)
        x = AveragePooling2D(pool_size=input_shape, strides=(1, 1), name='ave_pool/ecoc_' + str(id_branch))(out_3x3)

        # Softmax
        output_name = 'fc_OnevsOne_' + str(id_branch) + '/out'
        x = Flatten(name='fc_OnevsOne_' + str(id_branch) + '/flatten')(x)
        x = Dropout(0.5, name='fc_OnevsOne_' + str(id_branch) + '/drop')(x)
        out_node = Dense(nOutput, activation=activation, name=output_name)(x)

        return out_node

    def add_One_vs_One_3x3_double_Functional(self, input, input_shape, id_branch, nOutput=2, activation='softmax'):

        # 3x3 convolution
        out_3x3 = Convolution2D(64, 3, 3, name='3x3_1/ecoc_' + str(id_branch), activation='relu')(input)

        # Max Pooling
        x = MaxPooling2D(strides=(2, 2), pool_size=(2, 2), name='max_pool/ecoc_' + str(id_branch))(out_3x3)

        # 3x3 convolution
        x = Convolution2D(32, 3, 3, name='3x3_2/ecoc_' + str(id_branch), activation='relu')(x)

        # Softmax
        output_name = 'fc_OnevsOne_' + str(id_branch) + '/out'
        x = Flatten(name='fc_OnevsOne_' + str(id_branch) + '/flatten')(x)
        x = Dropout(0.5, name='fc_OnevsOne_' + str(id_branch) + '/drop')(x)
        out_node = Dense(nOutput, activation=activation, name=output_name)(x)

        return out_node

    def One_vs_One_Inception_v2(self, nOutput=2, input=[224, 224, 3]):
        """
            Builds a simple One_vs_One_Inception_v2 network with 2 inception layers (useful for ECOC models).
        """
        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Graph()
        # Input
        self.model.add_input(name='input', input_shape=input_shape)
        # Inception Ea
        out_Ea = self.__addInception('inceptionEa', 'input', 16, 8, 32, 8, 8, 8)
        # Inception Eb
        out_Eb = self.__addInception('inceptionEb', out_Ea, 8, 8, 16, 8, 4, 4)
        # Average Pooling    pool_size=(7,7)
        self.model.add_node(AveragePooling2D(pool_size=input_shape[1:], strides=(1, 1)), name='ave_pool/ECOC',
                            input=out_Eb)
        # Softmax
        self.model.add_node(Flatten(), name='loss_OnevsOne/classifier_flatten', input='ave_pool/ECOC')
        self.model.add_node(Dropout(0.5), name='loss_OnevsOne/drop', input='loss_OnevsOne/classifier_flatten')
        self.model.add_node(Dense(nOutput, activation='softmax'), name='loss_OnevsOne', input='loss_OnevsOne/drop')
        # Output
        self.model.add_output(name='loss_OnevsOne/output', input='loss_OnevsOne')

    def add_One_vs_One_Inception_v2(self, input, input_shape, id_branch, nOutput=2, activation='softmax'):
        """
            Builds a simple One_vs_One_Inception_v2 network with 2 inception layers on the top of the current model (useful for ECOC_loss models).
        """

        # Inception Ea
        out_Ea = self.__addInception('inceptionEa_' + str(id_branch), input, 16, 8, 32, 8, 8, 8)
        # Inception Eb
        out_Eb = self.__addInception('inceptionEb_' + str(id_branch), out_Ea, 8, 8, 16, 8, 4, 4)
        # Average Pooling    pool_size=(7,7)
        self.model.add_node(AveragePooling2D(pool_size=input_shape[1:], strides=(1, 1)),
                            name='ave_pool/ECOC_' + str(id_branch), input=out_Eb)
        # Softmax
        self.model.add_node(Flatten(),
                            name='fc_OnevsOne_' + str(id_branch) + '/flatten', input='ave_pool/ECOC_' + str(id_branch))
        self.model.add_node(Dropout(0.5),
                            name='fc_OnevsOne_' + str(id_branch) + '/drop',
                            input='fc_OnevsOne_' + str(id_branch) + '/flatten')
        output_name = 'fc_OnevsOne_' + str(id_branch)
        self.model.add_node(Dense(nOutput, activation=activation),
                            name=output_name, input='fc_OnevsOne_' + str(id_branch) + '/drop')

        return output_name

    def __addInception(self, id, input_layer, kernels_1x1, kernels_3x3_reduce, kernels_3x3, kernels_5x5_reduce,
                       kernels_5x5, kernels_pool_projection):
        """
            Adds an inception module to the model.

            :param id: string identifier of the inception layer
            :param input_layer: identifier of the layer that will serve as an input to the built inception module
            :param kernels_1x1: number of kernels of size 1x1                                      (1st branch)
            :param kernels_3x3_reduce: number of kernels of size 1x1 before the 3x3 layer          (2nd branch)
            :param kernels_3x3: number of kernels of size 3x3                                      (2nd branch)
            :param kernels_5x5_reduce: number of kernels of size 1x1 before the 5x5 layer          (3rd branch)
            :param kernels_5x5: number of kernels of size 5x5                                      (3rd branch)
            :param kernels_pool_projection: number of kernels of size 1x1 after the 3x3 pooling    (4th branch)
        """
        # Branch 1
        self.model.add_node(Convolution2D(kernels_1x1, 1, 1), name=id + '/1x1', input=input_layer)
        self.model.add_node(Activation('relu'), name=id + '/relu_1x1', input=id + '/1x1')

        # Branch 2
        self.model.add_node(Convolution2D(kernels_3x3_reduce, 1, 1), name=id + '/3x3_reduce', input=input_layer)
        self.model.add_node(Activation('relu'), name=id + '/relu_3x3_reduce', input=id + '/3x3_reduce')
        self.model.add_node(ZeroPadding2D((1, 1)), name=id + '/3x3_zeropadding', input=id + '/relu_3x3_reduce')
        self.model.add_node(Convolution2D(kernels_3x3, 3, 3), name=id + '/3x3', input=id + '/3x3_zeropadding')
        self.model.add_node(Activation('relu'), name=id + '/relu_3x3', input=id + '/3x3')

        # Branch 3
        self.model.add_node(Convolution2D(kernels_5x5_reduce, 1, 1), name=id + '/5x5_reduce', input=input_layer)
        self.model.add_node(Activation('relu'), name=id + '/relu_5x5_reduce', input=id + '/5x5_reduce')
        self.model.add_node(ZeroPadding2D((2, 2)), name=id + '/5x5_zeropadding', input=id + '/relu_5x5_reduce')
        self.model.add_node(Convolution2D(kernels_5x5, 5, 5), name=id + '/5x5', input=id + '/5x5_zeropadding')
        self.model.add_node(Activation('relu'), name=id + '/relu_5x5', input=id + '/5x5')

        # Branch 4
        self.model.add_node(ZeroPadding2D((1, 1)), name=id + '/pool_zeropadding', input=input_layer)
        self.model.add_node(MaxPooling2D((3, 3), strides=(1, 1)), name=id + '/pool', input=id + '/pool_zeropadding')
        self.model.add_node(Convolution2D(kernels_pool_projection, 1, 1), name=id + '/pool_proj', input=id + '/pool')
        self.model.add_node(Activation('relu'), name=id + '/relu_pool_proj', input=id + '/pool_proj')

        # Concat
        inputs_list = [id + '/relu_1x1', id + '/relu_3x3', id + '/relu_5x5', id + '/relu_pool_proj']
        out_name = id + '/concat'
        self.model.add_node(Activation('linear'), name=out_name, inputs=inputs_list, concat_axis=1)

        return out_name

    def __addInception_Functional(self, id, input_layer, kernels_1x1, kernels_3x3_reduce, kernels_3x3,
                                  kernels_5x5_reduce, kernels_5x5, kernels_pool_projection):
        """
            Adds an inception module to the model.

            :param id: string identifier of the inception layer
            :param input_layer: identifier of the layer that will serve as an input to the built inception module
            :param kernels_1x1: number of kernels of size 1x1                                      (1st branch)
            :param kernels_3x3_reduce: number of kernels of size 1x1 before the 3x3 layer          (2nd branch)
            :param kernels_3x3: number of kernels of size 3x3                                      (2nd branch)
            :param kernels_5x5_reduce: number of kernels of size 1x1 before the 5x5 layer          (3rd branch)
            :param kernels_5x5: number of kernels of size 5x5                                      (3rd branch)
            :param kernels_pool_projection: number of kernels of size 1x1 after the 3x3 pooling    (4th branch)
        """
        # Branch 1
        x_b1 = Convolution2D(kernels_1x1, 1, 1, name=id + '/1x1', activation='relu')(input_layer)

        # Branch 2
        x_b2 = Convolution2D(kernels_3x3_reduce, 1, 1, name=id + '/3x3_reduce', activation='relu')(input_layer)
        x_b2 = ZeroPadding2D((1, 1), name=id + '/3x3_zeropadding')(x_b2)
        x_b2 = Convolution2D(kernels_3x3, 3, 3, name=id + '/3x3', activation='relu')(x_b2)

        # Branch 3
        x_b3 = Convolution2D(kernels_5x5_reduce, 1, 1, name=id + '/5x5_reduce', activation='relu')(input_layer)
        x_b3 = ZeroPadding2D((2, 2), name=id + '/5x5_zeropadding')(x_b3)
        x_b3 = Convolution2D(kernels_5x5, 5, 5, name=id + '/5x5', activation='relu')(x_b3)

        # Branch 4
        x_b4 = ZeroPadding2D((1, 1), name=id + '/pool_zeropadding')(input_layer)
        x_b4 = MaxPooling2D((3, 3), strides=(1, 1), name=id + '/pool')(x_b4)
        x_b4 = Convolution2D(kernels_pool_projection, 1, 1, name=id + '/pool_proj', activation='relu')(x_b4)

        # Concat
        out_name = id + '/concat'
        out_node = merge([x_b1, x_b2, x_b3, x_b4], mode='concat', concat_axis=1, name=out_name)

        return [out_node, out_name]

    def add_One_vs_One_Merge(self, inputs_list, nOutput, activation='softmax'):

        self.model.add_node(Flatten(), name='ecoc_loss', inputs=inputs_list,
                            merge_mode='concat')  # join outputs from OneVsOne classifers
        self.model.add_node(Dropout(0.5), name='final_loss/drop', input='ecoc_loss')
        self.model.add_node(Dense(nOutput, activation=activation), name='final_loss',
                            input='final_loss/drop')  # apply final joint prediction

        # Outputs
        self.model.add_output(name='ecoc_loss/output', input='ecoc_loss')
        self.model.add_output(name='final_loss/output', input='final_loss')

        return ['ecoc_loss/output', 'final_loss/output']

    def add_One_vs_One_Merge_Functional(self, inputs_list, nOutput, activation='softmax'):

        # join outputs from OneVsOne classifers
        ecoc_loss_name = 'ecoc_loss'
        final_loss_name = 'final_loss/out'
        ecoc_loss = merge(inputs_list, name=ecoc_loss_name, mode='concat', concat_axis=1)
        drop = Dropout(0.5, name='final_loss/drop')(ecoc_loss)
        # apply final joint prediction
        final_loss = Dense(nOutput, activation=activation, name=final_loss_name)(drop)

        in_node = self.model.layers[0].name
        in_node = self.model.get_layer(in_node).output
        self.model = Model(input=in_node, output=[ecoc_loss, final_loss])
        # self.model = Model(input=in_node, output=['ecoc_loss', 'final_loss'])

        return [ecoc_loss_name, final_loss_name]

    def GAP(self, nOutput, input):
        """
            Creates a GAP network for object localization as described in the paper
                Zhou B, Khosla A, Lapedriza A, Oliva A, Torralba A.
                Learning Deep Features for Discriminative Localization.
                arXiv preprint arXiv:1512.04150. 2015 Dec 14.
            Outputs:
                'GAP/softmax' output of the final softmax classification
                'GAP/conv' output of the generated convolutional maps.
        """

        if len(input) == 3:
            input_shape = tuple([input[2]] + input[0:2])
        else:
            input_shape = tuple(input)

        self.model = Graph()

        # Input
        self.model.add_input(name='input', input_shape=input_shape)

        # Layers
        self.model.add_node(ZeroPadding2D((1, 1)), name='CAM_conv/zeropadding', input='input')
        self.model.add_node(Convolution2D(1024, 3, 3), name='CAM_conv', input='CAM_conv/zeropadding')
        self.model.add_node(Activation('relu'), name='CAM_conv/relu', input='CAM_conv')
        self.model.add_node(AveragePooling2D(pool_size=(14, 14)), name='GAP', input='CAM_conv/relu')
        self.model.add_node(Flatten(), name='GAP/flatten', input='GAP')
        self.model.add_node(Dense(nOutput, activation='softmax'), name='GAP/classifier_food_vs_nofood',
                            input='GAP/flatten')

        # Output
        self.model.add_output(name='GAP/softmax', input='GAP/classifier_food_vs_nofood')

    ##############################
    #       DENSE NETS
    ##############################

    def add_dense_block(self, in_layer, nb_layers, k, drop, init_weights):
        """
        Adds a Dense Block for the transition down path.

        # References
            Jegou S, Drozdzal M, Vazquez D, Romero A, Bengio Y.
            The One Hundred Layers Tiramisu: Fully Convolutional DenseNets for Semantic Segmentation.
            arXiv preprint arXiv:1611.09326. 2016 Nov 28.

        :param in_layer: input layer to the dense block.
        :param nb_layers: number of dense layers included in the dense block (see self.add_dense_layer() for information about the internal layers).
        :param k: growth rate. Number of additional feature maps learned at each layer.
        :param drop: dropout rate.
        :param init_weights: weights initialization function
        :return: output layer of the dense block
        """
        if K.image_dim_ordering() == 'th':
            axis = 1
        elif K.image_dim_ordering() == 'tf':
            axis = -1
        else:
            raise ValueError('Invalid dim_ordering:', K.image_dim_ordering)

        list_outputs = []
        prev_layer = in_layer
        for n in range(nb_layers):
            # Insert dense layer
            new_layer = self.add_dense_layer(prev_layer, k, drop, init_weights)
            list_outputs.append(new_layer)
            # Merge with previous layer
            prev_layer = merge([new_layer, prev_layer], mode='concat', concat_axis=axis)
        return merge(list_outputs, mode='concat', concat_axis=axis)

    def add_dense_layer(self, in_layer, k, drop, init_weights):
        """
        Adds a Dense Layer inside a Dense Block, which is composed of BN, ReLU, Conv and Dropout

        # References
            Jegou S, Drozdzal M, Vazquez D, Romero A, Bengio Y.
            The One Hundred Layers Tiramisu: Fully Convolutional DenseNets for Semantic Segmentation.
            arXiv preprint arXiv:1611.09326. 2016 Nov 28.

        :param in_layer: input layer to the dense block.
        :param k: growth rate. Number of additional feature maps learned at each layer.
        :param drop: dropout rate.
        :param init_weights: weights initialization function
        :return: output layer
        """

        out_layer = BatchNormalization(mode=2, axis=1)(in_layer)
        out_layer = Activation('relu')(out_layer)
        out_layer = Convolution2D(k, 3, 3, init=init_weights, border_mode='same')(out_layer)
        if drop > 0.0:
            out_layer = Dropout(drop)(out_layer)
        return out_layer

    def add_transitiondown_block(self, x,
                                 nb_filters_conv, pool_size, init_weights,
                                 nb_layers, growth, drop):
        """
        Adds a Transition Down Block. Consisting of BN, ReLU, Conv and Dropout, Pooling, Dense Block.

        # References
            Jegou S, Drozdzal M, Vazquez D, Romero A, Bengio Y.
            The One Hundred Layers Tiramisu: Fully Convolutional DenseNets for Semantic Segmentation.
            arXiv preprint arXiv:1611.09326. 2016 Nov 28.

        # Input layers parameters
        :param x: input layer.

        # Convolutional layer parameters
        :param nb_filters_conv: number of convolutional filters to learn.
        :param pool_size: size of the max pooling operation (2 in reference paper)
        :param init_weights: weights initialization function

        # Dense Block parameters
        :param nb_layers: number of dense layers included in the dense block (see self.add_dense_layer() for information about the internal layers).
        :param growth: growth rate. Number of additional feature maps learned at each layer.
        :param drop: dropout rate.

        :return: [output layer, skip connection name]
        """
        if K.image_dim_ordering() == 'th':
            axis = 1
        elif K.image_dim_ordering() == 'tf':
            axis = -1
        else:
            raise ValueError('Invalid dim_ordering:', K.image_dim_ordering)

        # Dense Block
        x_dense = self.add_dense_block(x, nb_layers, growth, drop,
                                       init_weights)  # (growth*nb_layers) feature maps added

        ## Concatenation and skip connection recovery for upsampling path
        skip = merge([x, x_dense], mode='concat', concat_axis=axis)

        # Transition Down
        x_out = BatchNormalization(mode=2, axis=1)(skip)
        x_out = Activation('relu')(x_out)
        x_out = Convolution2D(nb_filters_conv, 1, 1, init=init_weights, border_mode='same')(x_out)
        if drop > 0.0:
            x_out = Dropout(drop)(x_out)
        x_out = MaxPooling2D(pool_size=(pool_size, pool_size))(x_out)

        return [x_out, skip]

    def add_transitionup_block(self, x, skip_conn,
                               nb_filters_deconv, init_weights,
                               nb_layers, growth, drop):
        """
        Adds a Transition Up Block. Consisting of Deconv, Skip Connection, Dense Block.

        # References
            Jegou S, Drozdzal M, Vazquez D, Romero A, Bengio Y.
            The One Hundred Layers Tiramisu: Fully Convolutional DenseNets for Semantic Segmentation.
            arXiv preprint arXiv:1611.09326. 2016 Nov 28.

        # Input layers parameters
        :param x: input layer.
        :param skip_conn: list of layers to be used as skip connections.

        # Deconvolutional layer parameters
        :param nb_filters_deconv: number of deconvolutional filters to learn.
        :param init_weights: weights initialization function

        # Dense Block parameters
        :param nb_layers: number of dense layers included in the dense block (see self.add_dense_layer() for information about the internal layers).
        :param growth: growth rate. Number of additional feature maps learned at each layer.
        :param drop: dropout rate.

        :return: output layer
        """
        if K.image_dim_ordering() == 'th':
            axis = 1
        elif K.image_dim_ordering() == 'tf':
            axis = -1
        else:
            raise ValueError('Invalid dim_ordering:', K.image_dim_ordering)

        # Transition Up
        #x = Deconvolution2D(nb_filters_deconv, 3, 3, init=init_weights,
        #                             subsample=(2, 2), border_mode='same')(x)
        x = ArbitraryDeconvolution2D(nb_filters_deconv, 3, 3, [None, nb_filters_deconv, None, None],
                                     init=init_weights,
                                     subsample=(2, 2), border_mode='same')(x)

        # Skip connection concatenation
        x = merge([skip_conn, x], mode='concat', concat_axis=axis)
        # Dense Block
        x = self.add_dense_block(x, nb_layers, growth, drop, init_weights)  # (growth*nb_layers) feature maps added
        return x

    def Empty(self, nOutput, input):
        """
            Creates an empty Model_Wrapper (can be externally defined)
        """
        pass

    # ------------------------------------------------------- #
    #       SAVE/LOAD
    #           Auxiliary methods for saving and loading the model.
    # ------------------------------------------------------- #

    def __getstate__(self):
        """
            Behaviour applied when pickling a Model_Wrapper instance.
        """
        obj_dict = self.__dict__.copy()
        del obj_dict['model']
        # Remove also optimized search models if exist
        if 'model_init' in obj_dict:
            del obj_dict['model_init']
            del obj_dict['model_next']
        return obj_dict


# Backwards compatibility
CNN_Model = Model_Wrapper
