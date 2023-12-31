'''
this files trains a CBM
'''
import sys, os
import tqdm
import numpy as np
import seaborn as sns
import torch
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image
from torchvision import transforms
from IPython.display import Image as showImg
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Subset
from torch.utils.data import TensorDataset, DataLoader
import matplotlib.pyplot as plt
from copy import deepcopy
import matplotlib
import pandas as pd
from sklearn.model_selection import train_test_split
import argparse
from torch.optim import lr_scheduler
import torch.nn.functional as F
from functools import partial

###
FilePath = os.path.dirname(os.path.abspath(__file__))
RootPath = os.path.dirname(FilePath)
if RootPath not in sys.path: # parent directory
    sys.path = [RootPath] + sys.path
from lib.models import MLP, CBM
from lib.data import MIMIC_ahrf, SubColumn, MIMIC_train_transform, MIMIC_test_transform
from lib.data import SubAttr
from lib.train import train, train_step_xyc
from lib.eval import get_output, test_auc, plot_log, shap_net_x, shap_ccm_c, bootstrap
from lib.utils import birdfile2class, birdfile2idx, is_test_bird_idx, get_bird_bbox, get_bird_class, get_bird_part, get_part_location, get_multi_part_location, get_bird_name
from lib.utils import get_attribute_name, code2certainty, get_class_attributes, get_image_attributes, describe_bird
from lib.utils import get_attr_names

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--outputs_dir", default=f"outputs",
                        help="where to save all the outputs")
    parser.add_argument("--lr", default=0.01, type=float,
                        help="learning rate")
    parser.add_argument("--eval", action="store_true",
                        help="whether or not to eval the learned model")
    parser.add_argument("--add_s", action="store_true",
                        help="add S to C in concept prediction (Q5)")
    parser.add_argument("--ind", action="store_true",
                        help="whether or not to train independent CBM")
    parser.add_argument("--retrain", action="store_true",
                        help="retrain using all train val data")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed for reproducibility")
    parser.add_argument("--transform", default="cbm",
                        help="transform mode to use")
    parser.add_argument("--d_noise", default=0, type=int,
                        help="wrong expert dimensions (noise dimensions in c)")
    parser.add_argument("--lr_step", type=int, default=1000,
                        help="learning rate decay steps")
    parser.add_argument("--n_epochs", type=int, default=100,
                        help="max number of epochs to train")
    parser.add_argument("--use_aux", action="store_true",
                        help="auxilliary loss for inception")
    parser.add_argument("--c_model_path", type=str,
                        default="outputs/3b52388a27ea11ecb773ac1f6b24a434/standard",
                        help="concept model path starting from root (ignore .pt)")
    # shortcut related
    parser.add_argument("-s", "--shortcut", default="clean",
                        help="shortcut transform to use; clean: no shortcut; noise: shortcut dependent on y; else: shortcut dependent on yhat computed from the model path")
    parser.add_argument("-t", "--threshold", default=1.0, type=float,
                        help="shortcut threshold to use (1 always Y dependent, 0 ind)")
    parser.add_argument("--n_shortcuts", default=2, type=int,
                        help="number of shortcuts")
    
    args = parser.parse_args()
    print(args)
    return args

def cbm(flags, concept_model_path,
        loader_xy, loader_xy_eval, loader_xy_te, loader_xy_val=None,
        n_epochs=10, report_every=1, lr_step=1000, net_s=None,
        independent=False,
        device='cuda', savepath=None, use_aux=False):
    '''
    loader_xy_eval is the evaluation of loader_xy
    if loader_xy_val: use early stopping, otherwise train for the number of epochs
    '''
    # regular model
    x2c = torch.load(f'{RootPath}/{concept_model_path}.pt')
    x2c.aux_logits = False
    x2c.fc = nn.Identity()
    fc = nn.Linear(2048, 1) # binary for mimic

    net = CBM(x2c, fc, c_no_grad=True)
    net.to(device)

    print('task auc before training: {:.1f}%'.format(
        run_test(net, loader_xy_te) * 100))
    
    # criterion = lambda o_y, y: F.cross_entropy(o_y, y)
    # criterion = lambda o_y, y: nn.BCEWithLogitsLoss(pos_weight=torch.tensor([10]).long().to(device))(o_y, y.unsqueeze(1).long())
    def criterion(o_y, y):
        b = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([10]).to(device))
        return b(o_y, y.unsqueeze(1).float())
    
    # train
    opt = optim.SGD(net.parameters(), lr=flags.lr, momentum=0.9)
    # opt = optim.Adam(net.parameters())
    scheduler = lr_scheduler.StepLR(opt, step_size=lr_step)

    run_train = lambda **kwargs: train(net, loader_xy, opt, criterion=criterion,
                                       # shortcut specific
                                       shortcut_mode = flags.shortcut,
                                       shortcut_threshold = flags.threshold,
                                       n_shortcuts = flags.n_shortcuts,
                                       net_shortcut = net_s,
                                       # shortcut specific ends
                                       independent=independent,
                                       n_epochs=n_epochs, report_every=report_every,
                                       device=device, savepath=savepath,
                                       scheduler=scheduler, **kwargs)

    if loader_xy_val:
        log  = run_train(
            report_dict={'val auc': (lambda m: run_test(m, loader_xy_val) * 100, 'max'),
                         'train auc': (lambda m: run_test(m, loader_xy_eval) * 100,
                                       'max')},
                    early_stop_metric='val auc')
    else:
        log = run_train(
            report_dict={'test auc': (lambda m: run_test(m, loader_xy_te) * 100, 'max'),
                         'train auc': (lambda m: run_test(m, loader_xy_eval) * 100,
                                       'max')})


    print('task auc after training: {:.1f}%'.format(run_test(net, loader_xy_te) * 100))
    return net

if __name__ == '__main__':
    flags = get_args()
    model_name = f"{RootPath}/{flags.outputs_dir}/cbm"
    print(model_name)

    mimic = MIMIC_ahrf('chf_scale')
    train_indices = np.where(mimic.df['split'] == "train")[0]
    val_indices = np.where(mimic.df['split'] == "valid")[0]
    test_indices = np.where(mimic.df['split'] == "test")[0]

    # define dataloader: mimic_train_eval is used to evaluate training data
    mimic_train = MIMIC_train_transform(Subset(mimic, train_indices), mode=flags.transform)
    mimic_val = MIMIC_test_transform(Subset(mimic, val_indices),  mode=flags.transform)
    mimic_test = MIMIC_test_transform(Subset(mimic, test_indices), mode=flags.transform)
    mimic_train_eval = MIMIC_test_transform(Subset(mimic, train_indices), mode=flags.transform)

    # dataset
    subcolumn = lambda d: SubColumn(d, ['x', 'y'])
    load = lambda d, shuffle: DataLoader(subcolumn(d), batch_size=32,
                                shuffle=shuffle, num_workers=8)
    loader_xy = load(mimic_train, True)
    loader_xy_val = load(mimic_val, False)
    loader_xy_te = load(mimic_test, False)
    loader_xy_eval = load(mimic_train_eval, False)
    
    print(f"# train: {len(mimic_train)}, # val: {len(mimic_val)}, # test: {len(mimic_test)}")

    # shortcut
    if flags.shortcut not in ['clean', 'noise']:
        net_s = torch.load(flags.shortcut)
    else:
        net_s = None

    run_train = lambda **kwargs: cbm(
        flags, flags.c_model_path,
        loader_xy, loader_xy_eval,
        loader_xy_te, net_s=net_s,
        n_epochs=flags.n_epochs, report_every=1,
        lr_step=flags.lr_step,
        savepath=model_name, use_aux=flags.use_aux,
        independent=flags.ind, **kwargs)
    run_test = partial(test_auc, 
                       device='cuda',
                       # shortcut specific
                       shortcut_mode = flags.shortcut,
                       shortcut_threshold = flags.threshold,
                       n_shortcuts = flags.n_shortcuts,
                       net_shortcut = net_s)
    
    if flags.eval:
        net = torch.load(f'{model_name}.pt')
        print('task auc after training: {:.1f}%'.format(
            run_test(net,
                     loader_xy_te) * 100))
    elif flags.retrain:
        mimic_train = MIMIC_train_transform(Subset(mimic, train_val_indices),
                                        mode=flags.transform)
        mimic_train_eval = MIMIC_test_transform(Subset(mimic, train_val_indices),
                                             mode=flags.transform)
        loader_xy = load(mimic_train, True)
        loader_xy_eval = load(mimic_train_eval, False)

        net = run_train()
    else:
        net = run_train(loader_xy_val=loader_xy_val)
