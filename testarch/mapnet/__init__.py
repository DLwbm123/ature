import os
import traceback

import torch
import torch.optim as optim

from utils import auto_split as asp
from utils.measurements import ScoreAccumulator
from ..mapnet.mapnet_bee import MAPNetBee
from ..mapnet.mapnet_dataloader import PatchesGenerator
from ..mapnet.model import MapUNet


def run(runs, transforms):
    for R in runs:
        for k, folder in R['Dirs'].items():
            os.makedirs(folder, exist_ok=True)

        R['acc'] = ScoreAccumulator()
        for split in os.listdir(R['Dirs']['splits_json']):
            splits = asp.load_split_json(os.path.join(R['Dirs']['splits_json'], split))
            R['checkpoint_file'] = split + '.tar'

            model = MapUNet(R['Params']['num_channels'], R['Params']['num_classes'])
            optimizer = optim.Adam(model.parameters(), lr=R['Params']['learning_rate'])
            if R['Params']['distribute']:
                model = torch.nn.DataParallel(model)
                model.float()
                optimizer = optim.Adam(model.module.parameters(), lr=R['Params']['learning_rate'])

            try:
                trainer = MAPNetBee(model=model, conf=R, optimizer=optimizer)

                if R.get('Params').get('mode') == 'train':
                    train_loader = PatchesGenerator.get_loader(conf=R, images=splits['train'], transforms=transforms,
                                                               mode='train')
                    val_loader = PatchesGenerator.get_loader_per_img(conf=R, images=splits['validation'],
                                                                     mode='validation')
                    trainer.train(data_loader=train_loader, validation_loader=val_loader,
                                  epoch_run=trainer.epoch_dice_loss)

                trainer.resume_from_checkpoint(parallel_trained=R.get('Params').get('parallel_trained'))
                test_loader = PatchesGenerator.get_loader_per_img(conf=R, images=splits['test'], mode='test',
                                                                  transforms=transforms)

                trainer.test(data_loaders=test_loader, gen_images=True)
            except Exception as e:
                traceback.print_exc()

        print(R['acc'].get_prfa())
        f = open(R['Dirs']['logs'] + os.sep + 'score.txt', "w")
        f.write(', '.join(str(s) for s in R['acc'].get_prfa()))
        f.close()
