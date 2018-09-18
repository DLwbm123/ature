import os
import random
from random import shuffle

import numpy as np

import utils.img_utils as imgutils
from commons.IMAGE import Image
from neuralnet.datagen import Generator
from neuralnet.utils.measurements import get_best_f1_thr

sep = os.sep


class PatchesGenerator(Generator):
    def __init__(self, **kwargs):
        super(PatchesGenerator, self).__init__(**kwargs)
        self.patch_shape = self.run_conf.get('Params').get('patch_shape')
        # self.patch_offset = self.run_conf.get('Params').get('patch_offset')
        self.expand_by = self.run_conf.get('Params').get('expand_patch_by')
        self.est_thr = self.run_conf.get('Params').get('est_threshold', 50)
        self._load_indices()
        print('Patches:', self.__len__())

    def _load_indices(self):
        for ID, img_file in enumerate(self.images):

            img_obj = self._get_image_obj(img_file)

            est = img_obj.res['est']
            all_est_ixes = list(zip(*np.where(est == 255)))
            best_est_indices = list(
                imgutils.get_chunk_indices_by_index(est.shape, self.patch_shape, indices=all_est_ixes[::15]))

            for chunk_ix in best_est_indices:
                self.indices.append([ID] + chunk_ix)
            self.image_objects[ID] = img_obj
        if self.shuffle_indices:
            shuffle(self.indices)

    def _get_image_obj(self, img_file=None):
        img_obj = Image()
        img_obj.load_file(data_dir=self.image_dir,
                          file_name=img_file, num_channels=1)
        if self.mask_getter is not None:
            img_obj.load_mask(mask_dir=self.mask_dir,
                              fget_mask=self.mask_getter,
                              erode=True)
        if self.truth_getter is not None:
            img_obj.load_ground_truth(gt_dir=self.truth_dir,
                                      fget_ground_truth=self.truth_getter)

        if len(img_obj.image_arr.shape) == 3:
            img_obj.working_arr = img_obj.image_arr[:, :, 1]
        elif len(img_obj.image_arr.shape) == 2:
            img_obj.working_arr = img_obj.image_arr

        if img_obj.mask is not None:
            x = np.logical_and(True, img_obj.mask == 255)
            img_obj.working_arr[img_obj.mask == 0] = img_obj.working_arr[x].mean()

        img_obj.res['est'] = img_obj.working_arr.copy()
        img_obj.res['est'][img_obj.res['est'] >= self.est_thr] = 255
        img_obj.res['est'][img_obj.res['est'] < self.est_thr] = 0

        return img_obj

    def __getitem__(self, index):
        ID, row_from, row_to, col_from, col_to = self.indices[index]

        img_arr = self.image_objects[ID].working_arr.copy()
        gt = self.image_objects[ID].ground_truth.copy()

        prob_map = img_arr[row_from:row_to, col_from:col_to]
        y = gt[row_from:row_to, col_from:col_to]

        best_score1, best_thr1 = get_best_f1_thr(prob_map, y)

        p, q, r, s, pad = imgutils.expand_and_mirror_patch(full_img_shape=img_arr.shape,
                                                           orig_patch_indices=[row_from, row_to, col_from, col_to],
                                                           expand_by=self.expand_by)
        img_tensor = np.pad(img_arr[p:q, r:s], pad, 'reflect')

        if self.mode == 'train' and random.uniform(0, 1) <= 0.5:
            img_tensor = np.flip(img_tensor, 0)
            y = np.flip(y, 0)
            prob_map = np.flip(prob_map, 0)

        if self.mode == 'train' and random.uniform(0, 1) <= 0.5:
            img_tensor = np.flip(img_tensor, 1)
            y = np.flip(y, 1)
            prob_map = np.flip(prob_map, 1)

        img_tensor = img_tensor[..., None]
        if self.transforms is not None:
            img_tensor = self.transforms(img_tensor)

        y[y == 255] = 1
        return {'ID': ID, 'inputs': img_tensor,
                'clip_ix': np.array([row_from, row_to, col_from, col_to]),
                'y_thresholds': best_thr1,
                'prob_map': prob_map.copy(),
                'truth': y.copy()}
