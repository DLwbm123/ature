import os
from random import randint as it

import PIL.Image as IMG
import numpy as np
import torch
import torch.nn.functional as F

from neuralnet.torchtrainer import NNTrainer
from neuralnet.utils.measurements import ScoreAccumulator

sep = os.sep


class PatchNetTrainer(NNTrainer):
    def __init__(self, **kwargs):
        NNTrainer.__init__(self, **kwargs)

    def train(self, optimizer=None, data_loader=None, validation_loader=None):

        if validation_loader is None:
            raise ValueError('Please provide validation loader.')

        logger = NNTrainer.get_logger(self.train_log_file,
                                      header='ID,EPOCH,BATCH,PRECISION,RECALL,F1,ACCURACY,LOSS')

        val_logger = NNTrainer.get_logger(self.validation_log_file,
                                          header='ID,PRECISION,RECALL,F1,ACCURACY')

        print('Training...')
        for epoch in range(1, self.epochs + 1):
            self.model.train()
            score_acc = ScoreAccumulator()
            running_loss = 0.0
            self._adjust_learning_rate(optimizer=optimizer, epoch=epoch)
            for i, data in enumerate(data_loader, 1):
                inputs, labels = data['inputs'].to(self.device).float(), data['labels'].to(self.device).long()

                optimizer.zero_grad()
                outputs = self.model(inputs)
                _, predicted = torch.max(outputs, 1)
                w = torch.tensor([it(1, 10000), it(1, 10000)]).to(self.device).float()
                loss = F.nll_loss(outputs, labels, weight=w)
                loss.backward()
                optimizer.step()

                current_loss = loss.item()
                running_loss += current_loss
                p, r, f1, a = score_acc.reset().add_tensor(predicted, labels).get_prfa()
                if i % self.log_frequency == 0:
                    print('Epochs[%d/%d] Batch[%d/%d] loss:%.5f pre:%.3f rec:%.3f f1:%.3f acc:%.3f' %
                          (
                              epoch, self.epochs, i, data_loader.__len__(), running_loss / self.log_frequency, p, r, f1,
                              a))
                    running_loss = 0.0

                self.flush(logger, ','.join(str(x) for x in [0, epoch, i, p, r, f1, a, current_loss]))

            self.plot_train(file=self.train_log_file, batches_per_epochs=data_loader.__len__(), keys=['LOSS', 'F1'])
            if epoch % self.validation_frequency == 0:
                self.evaluate(data_loaders=validation_loader, logger=val_logger, gen_images=False)

            self.plot_val(self.validation_log_file, batches_per_epoch=len(validation_loader))

        try:
            logger.close()
            val_logger.close()
        except IOError:
            pass

    def evaluate(self, data_loaders=None, logger=None, gen_images=False):
        assert (logger is not None), 'Please Provide a logger'
        self.model.eval()

        print('\nEvaluating...')
        with torch.no_grad():
            eval_score = 0.0

            for loader in data_loaders:
                img_obj = loader.dataset.image_objects[0]
                segmented_img = torch.LongTensor(*img_obj.working_arr.shape).fill_(0).to(self.device)
                gt = torch.LongTensor(img_obj.ground_truth).to(self.device)
                fill_in = torch.LongTensor(img_obj.res['fill_in']).to(self.device)
                gt_mid = torch.LongTensor(img_obj.res['gt_mid']).to(self.device)

                for i, data in enumerate(loader, 1):
                    inputs, labels = data['inputs'].float().to(self.device), data['labels'].float().to(self.device)
                    IJs = data['IJs'].int().to(self.device)

                    outputs = self.model(inputs)
                    _, predicted = torch.max(outputs, 1)

                    for j in range(predicted.shape[0]):
                        x, y = IJs[j]
                        segmented_img[x, y] += predicted[j]
                    print('Batch: ', i, end='\r')

                img_score = ScoreAccumulator()
                if gen_images:
                    segmented_img[segmented_img != fill_in] = 255
                    segmented_img = segmented_img.cpu().numpy()
                    img_score.add_array(segmented_img, img_obj.ground_truth)
                    IMG.fromarray(np.array(segmented_img, dtype=np.uint8)).save(
                        os.path.join(self.log_dir, img_obj.file_name.split('.')[0] + '.png'))
                else:
                    img_score.add_tensor(segmented_img, gt_mid)
                    eval_score += img_score.get_prfa()[1]

                prf1a = img_score.get_prfa()
                print(img_obj.file_name, ' PRF1A', prf1a)
                self.flush(logger, ','.join(str(x) for x in [img_obj.file_name, 1, 0, 0] + prf1a))

        self._save_if_better(score=eval_score / len(data_loaders))