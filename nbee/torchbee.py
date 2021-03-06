"""
### author: Aashis Khanal
### sraashis@gmail.com
### date: 9/10/2018
"""

import os
import random as rd
import sys

import numpy as np
import torch
import torch.nn.functional as F

from utils.loss import dice_loss as l
from utils.measurements import ScoreAccumulator


class NNBee:

    def __init__(self, conf=None, model=None, optimizer=None):

        # Initialize parameters and directories before-hand so that we can clearly track which ones are used
        self.conf = conf
        self.log_dir = self.conf.get('Dirs').get('logs', 'net_logs')
        self.epochs = self.conf.get('Params').get('epochs', 100)
        self.log_frequency = self.conf.get('Params').get('log_frequency', 10)
        self.validation_frequency = self.conf.get('Params').get('validation_frequency', 1)
        self.mode = self.conf.get('Params').get('mode', 'test')

        # Initialize necessary logging conf
        self.checkpoint_file = os.path.join(self.log_dir, self.conf.get('checkpoint_file'))

        self.log_headers = self.get_log_headers()
        _log_key = self.conf.get('checkpoint_file').split('.')[0]
        self.test_logger = NNBee.get_logger(log_file=os.path.join(self.log_dir, _log_key + '-TEST.csv'),
                                            header=self.log_headers.get('test', ''))
        if self.mode == 'train':
            self.train_logger = NNBee.get_logger(log_file=os.path.join(self.log_dir, _log_key + '-TRAIN.csv'),
                                                 header=self.log_headers.get('train', ''))
            self.val_logger = NNBee.get_logger(log_file=os.path.join(self.log_dir, _log_key + '-VAL.csv'),
                                               header=self.log_headers.get('validation', ''))

        #  Function to initialize class weights, default is [1, 1]
        self.dparm = self.conf.get("Funcs").get('dparm')
        if not self.dparm:
            self.dparm = lambda x: [1.0, 1.0]

        # Handle gpu/cpu
        if torch.cuda.is_available():
            self.device = torch.device("cuda" if self.conf['Params'].get('use_gpu', False) else "cpu")
        else:
            print('### GPU not found.')
            self.device = torch.device("cpu")

        # Initialization to save model
        self.model = model.to(self.device)
        self.optimizer = optimizer
        self.model_trace = []
        self.checkpoint = {'total_epochs:': 0, 'epochs': 0, 'state': None, 'score': 0.0, 'model': 'EMPTY'}
        self.patience = self.conf.get('Params').get('patience', 35)

    def test(self, data_loaders=None, gen_images=True):
        print('Running test')
        self.model.eval()
        score = ScoreAccumulator()
        self._eval(data_loaders=data_loaders, gen_images=gen_images, score_acc=score, logger=self.test_logger)
        self._on_test_end(log_file=self.test_logger.name)
        if not self.test_logger and not self.test_logger.closed:
            self.test_logger.close()

    def _on_test_end(self, **kw):
        pass

    def train(self, data_loader=None, validation_loader=None, epoch_run=None):
        print('Training...')
        for epoch in range(1, self.epochs + 1):
            self._adjust_learning_rate(epoch=epoch)
            self.checkpoint['total_epochs'] = epoch

            # Run one epoch
            epoch_run(epoch=epoch, data_loader=data_loader)

            self._on_epoch_end(data_loader=data_loader, log_file=self.train_logger.name)

            # Validation_frequency is the number of epoch until validation
            if epoch % self.validation_frequency == 0:
                print('Running validation..')
                self.model.eval()
                val_score = ScoreAccumulator()
                self._eval(data_loaders=validation_loader, gen_images=False, score_acc=val_score,
                           logger=self.val_logger)
                self._on_validation_end(data_loader=validation_loader, log_file=self.val_logger.name)
                if self.early_stop(patience=self.patience):
                    return

        if not self.train_logger and not self.train_logger.closed:
            self.train_logger.close()
        if not self.val_logger and not self.val_logger.closed:
            self.val_logger.close()

    def _on_epoch_end(self, **kw):
        pass

    def _on_validation_end(self, **kw):
        pass

    def get_log_headers(self):
        # EXAMPLE:
        # return {
        #     'train': 'ID,EPOCH,BATCH,PRECISION,RECALL,F1,ACCURACY,LOSS',
        #     'validation': 'ID,PRECISION,RECALL,F1,ACCURACY',
        #     'test': 'ID,PRECISION,RECALL,F1,ACCURACY'
        # }
        raise NotImplementedError('Must be implemented to use.')

    def _eval(self, data_loaders=None, logger=None, gen_images=False, score_acc=None):
        return NotImplementedError('------Evaluation step can vary a lot.. Needs to be implemented.-------')

    def resume_from_checkpoint(self, parallel_trained=False):
        try:
            if parallel_trained:
                from collections import OrderedDict
                new_state_dict = OrderedDict()
                for k, v in self.checkpoint['state'].items():
                    name = k[7:]  # remove `module.`
                    new_state_dict[name] = v
                # load params
                self.model.load_state_dict(new_state_dict)
            else:
                self.model.load_state_dict(self.checkpoint['state'])
        except Exception as e:
            print('ERROR: ' + str(e))

    def _save_if_better(self, score=None):

        if self.mode == 'test':
            return

        if score > self.checkpoint['score']:
            print('Score improved: ',
                  str(self.checkpoint['score']) + ' to ' + str(score) + ' BEST CHECKPOINT SAVED')
            self.checkpoint['state'] = self.model.state_dict()
            self.checkpoint['epochs'] = self.checkpoint['total_epochs']
            self.checkpoint['score'] = score
            self.checkpoint['model'] = str(self.model)
            torch.save(self.checkpoint, self.checkpoint_file)
        else:
            print('Score did not improve:' + str(score) + ' BEST: ' + str(self.checkpoint['score']) + ' EP: ' + (
                str(self.checkpoint['epochs'])))

    def early_stop(self, patience=35):
        return self.checkpoint['total_epochs'] - self.checkpoint['epochs'] >= patience * self.validation_frequency

    @staticmethod
    def get_logger(log_file=None, header=''):

        if os.path.isfile(log_file):
            print('### CRITICAL!!! ' + log_file + '" already exists.')
            ip = input('Override? [Y/N]: ')
            if ip == 'N' or ip == 'n':
                sys.exit(1)

        file = open(log_file, 'w')
        NNBee.flush(file, header)
        return file

    @staticmethod
    def flush(logger, msg):
        if logger is not None:
            logger.write(msg + '\n')
            logger.flush()

    def _adjust_learning_rate(self, epoch):
        if epoch % 30 == 0:
            for param_group in self.optimizer.param_groups:
                if param_group['lr'] >= 1e-5:
                    param_group['lr'] = param_group['lr'] * 0.7

    @staticmethod
    def plot_column_keys(file, batches_per_epoch, title='', keys=[]):
        """
        This method plots all desired columns, specified in key, from log file
        :param file:
        :param batches_per_epoch:
        :param title:
        :param keys:
        :return:
        """
        from viz.nviz import plot
        for k in keys:
            plot(file=file, title=title, y=k, save=True,
                 x_tick_skip=batches_per_epoch)

    '''
    ######################################################################################
    Below are the functions specific to loss function and training strategy
    These functions should be passed while calling *TorchTrainer.train() from main.py
    ######################################################################################
    '''

    def epoch_ce_loss(self, **kw):
        """
        One epoch implementation of binary cross-entropy loss
        :param kw:
        :return:
        """
        running_loss = 0.0
        score_acc = ScoreAccumulator()
        for i, data in enumerate(kw['data_loader'], 1):
            inputs, labels = data['inputs'].to(self.device).float(), data['labels'].to(self.device).long()
            self.optimizer.zero_grad()
            outputs = self.model(inputs)
            _, predicted = torch.max(outputs, 1)

            loss = F.nll_loss(outputs, labels, weight=torch.FloatTensor(self.dparm(self.conf)).to(self.device))
            loss.backward()
            self.optimizer.step()

            current_loss = loss.item()
            running_loss += current_loss
            p, r, f1, a = score_acc.reset().add_tensor(predicted, labels).get_prfa()

            if i % self.log_frequency == 0:
                print('Epochs[%d/%d] Batch[%d/%d] loss:%.5f pre:%.3f rec:%.3f f1:%.3f acc:%.3f' %
                      (
                          kw['epoch'], self.epochs, i, kw['data_loader'].__len__(),
                          running_loss / self.log_frequency, p, r, f1,
                          a))
                running_loss = 0.0
            self.flush(self.train_logger,
                       ','.join(str(x) for x in [0, kw['epoch'], i, p, r, f1, a, current_loss]))

    def epoch_dice_loss(self, **kw):
        score_acc = ScoreAccumulator()
        running_loss = 0.0
        for i, data in enumerate(kw['data_loader'], 1):
            inputs, labels = data['inputs'].to(self.device).float(), data['labels'].to(self.device).long()
            # weights = data['weights'].to(self.device)

            self.optimizer.zero_grad()
            outputs = self.model(inputs)
            _, predicted = torch.max(outputs, 1)

            # Balancing imbalanced class as per computed weights from the dataset
            # w = torch.FloatTensor(2).random_(1, 100).to(self.device)
            # wd = torch.FloatTensor(*labels.shape).uniform_(0.1, 2).to(self.device)

            loss = l.dice_loss(outputs[:, 1, :, :], labels, beta=rd.choice(np.arange(1, 2, 0.1).tolist()))
            loss.backward()
            self.optimizer.step()

            current_loss = loss.item()
            running_loss += current_loss
            p, r, f1, a = score_acc.reset().add_tensor(predicted, labels).get_prfa()
            if i % self.log_frequency == 0:
                print('Epochs[%d/%d] Batch[%d/%d] loss:%.5f pre:%.3f rec:%.3f f1:%.3f acc:%.3f' %
                      (
                          kw['epoch'], self.epochs, i, kw['data_loader'].__len__(), running_loss / self.log_frequency,
                          p, r, f1,
                          a))
                running_loss = 0.0

            self.flush(self.train_logger, ','.join(str(x) for x in [0, kw['epoch'], i, p, r, f1, a, current_loss]))

    def epoch_mse_loss(self, **kw):
        running_loss = 0.0
        for i, data in enumerate(kw['data_loader'], 1):
            inputs, labels = data['inputs'].to(self.device).float(), data['labels'].to(self.device).float()

            self.optimizer.zero_grad()
            outputs = self.model(inputs)
            _, predicted = torch.max(outputs, 1)

            if len(labels.shape) == 3:
                labels = torch.unsqueeze(labels, 1)

            loss = F.mse_loss(outputs, labels)
            loss.backward()
            self.optimizer.step()

            current_loss = loss.item()
            running_loss += current_loss

            if i % self.log_frequency == 0:
                print('Epochs[%d/%d] Batch[%d/%d] MSE loss:%.5f ' %
                      (
                          kw['epoch'], self.epochs, i, kw['data_loader'].__len__(), running_loss / self.log_frequency))
                running_loss = 0.0

            self.flush(self.train_logger, ','.join(str(x) for x in [0, kw['epoch'], i, current_loss]))
