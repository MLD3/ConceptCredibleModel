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

###
FilePath = os.path.dirname(os.path.abspath(__file__))
RootPath = os.path.dirname(FilePath)
if RootPath not in sys.path: # parent directory
    sys.path = [RootPath] + sys.path
from lib.models import MLP
from lib.data import small_CUB, CUB, SubColumn, CUB_train_transform, CUB_test_transform
from lib.train import train
from lib.eval import get_output, test, plot_log, shap_net_x, shap_ccm_c, bootstrap
from lib.utils import birdfile2class, birdfile2idx, is_test_bird_idx, get_bird_bbox, get_bird_class, get_bird_part, get_part_location, get_multi_part_location, get_bird_name
from lib.utils import get_attribute_name, code2certainty, get_class_attributes, get_image_attributes, describe_bird

cub = CUB()

train_val_indices = [i for i in range(len(cub)) if not is_test_bird_idx(birdfile2idx(cub.images_path[i]))]
train_val_labels = [cub.labels[i] for i in range(len(cub)) if not is_test_bird_idx(birdfile2idx(cub.images_path[i]))]
val_ratio = 0.2
train_indices, val_indices = train_test_split(train_val_indices, test_size=val_ratio, stratify=train_val_labels)

# train_indices = [i for i in range(len(cub)) if not is_test_bird_idx(birdfile2idx(cub.images_path[i]))]
test_indices = [i for i in range(len(cub)) if is_test_bird_idx(birdfile2idx(cub.images_path[i]))]
cub_train = CUB_train_transform(Subset(cub, train_indices))
cub_val = CUB_test_transform(Subset(cub, val_indices))
cub_test = CUB_test_transform(Subset(cub, test_indices))

# accuracy
acc_criterion = lambda o, y: (o.argmax(1) == y).float()

# dataset
loader_xy = DataLoader(SubColumn(cub_train, ['x', 'y']), batch_size=32, shuffle=True, num_workers=8)
loader_xy_val = DataLoader(SubColumn(cub_val, ['x', 'y']), batch_size=32, shuffle=False, num_workers=8)
loader_xy_te = DataLoader(SubColumn(cub_test, ['x', 'y']), batch_size=32, shuffle=False, num_workers=8)

print(f"# train: {len(cub_train)}, # val: {len(cub_val)}, # test: {len(cub_test)}")

def standard_model(loader_xy, loader_xy_val, loader_xy_te, n_epochs=10, report_every=1, plot=False, device='cuda'):
    # regular model
    net = torch.hub.load('pytorch/vision:v0.9.0', 'inception_v3', pretrained=True)
    net.fc = nn.Linear(2048, 200) # 200 bird classes
    net.to(device)
    print('task acc before training: {:.1f}%'.format(test(net, loader_xy_te, acc_criterion, device=device) * 100))
    
    # train
    opt = optim.SGD(net.parameters(), lr=0.01, momentum=0.9, weight_decay=0.0004)
    log = train(net, loader_xy, opt, n_epochs=n_epochs, report_every=report_every,
                device=device, savepath=f"{RootPath}/models/standard",
                report_dict={'val acc': (lambda m: test(m, loader_xy_val, acc_criterion, device=device) * 100, 'max'),
                             'train acc': (lambda m: test(m, loader_xy, acc_criterion, device=device) * 100, 'max')},
                early_stop_metric='val acc')
    if plot: plot_log(log)
    print('task acc after training: {:.1f}%'.format(test(net, loader_xy_te, acc_criterion, device=device) * 100))        
    return net

standard_net = standard_model(loader_xy, loader_xy_val, loader_xy_te, n_epochs=100, report_every=1)

    