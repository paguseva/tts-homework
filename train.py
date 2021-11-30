import argparse
import collections
import warnings

import numpy as np
import torch

import tts_hw.loss as module_loss
import tts_hw.model as module_arch
from tts_hw.alignment.aligner import GraphemeAligner
from tts_hw.datasets.utils import get_dataloaders
from tts_hw.featurizer.featurizer import MelSpectrogram
from tts_hw.trainer import Trainer
from tts_hw.utils import prepare_device
from tts_hw.utils.parse_config import ConfigParser
from tts_hw.vocoders.waveglow import Vocoder

warnings.filterwarnings("ignore", category=UserWarning)

# fix random seeds for reproducibility
SEED = 123
torch.manual_seed(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
np.random.seed(SEED)


def main(config):
    logger = config.get_logger("train")

    # vocoder
    vocoder = Vocoder("./data/waveglow_256channels_universal_v5.pt")

    # melspec
    melspec = MelSpectrogram(**config["preprocessing"]["melspec"])

    # grapheme aligner
    aligner = GraphemeAligner(**config["preprocessing"]["aligner"])

    # build model architecture, then print to console
    model = config.init_obj(config["arch"], module_arch)
    logger.info(model)

    # prepare for (multi-device) GPU training
    device, device_ids = prepare_device(config["n_gpu"])
    vocoder = vocoder.to(device)
    aligner = aligner.to(device)
    model = model.to(device)
    if len(device_ids) > 1:
        model = torch.nn.DataParallel(model, device_ids=device_ids)

    # setup data_loader instances
    dataloaders = get_dataloaders(config, aligner, melspec)

    # get function handles of loss and metrics
    loss_module = config.init_obj(config["loss"], module_loss).to(device)

    # build optimizer, learning rate scheduler. delete every lines containing lr_scheduler for disabling scheduler
    trainable_params = filter(lambda p: p.requires_grad, model.parameters())
    optimizer = config.init_obj(config["optimizer"], torch.optim, trainable_params)
    lr_scheduler = config.init_obj(config["lr_scheduler"], torch.optim.lr_scheduler, optimizer)

    trainer = Trainer(
        model,
        loss_module,
        optimizer,
        config=config,
        device=device,
        vocoder=vocoder,
        data_loader=dataloaders["train"],
        valid_data_loader=dataloaders["val"],
        lr_scheduler=lr_scheduler,
        len_epoch=config["trainer"].get("len_epoch", None),
        sr=config["trainer"].get("sr", 22050),
    )

    trainer.train()


if __name__ == "__main__":
    args = argparse.ArgumentParser(description="PyTorch Template")
    args.add_argument(
        "-c",
        "--config",
        default=None,
        type=str,
        help="config file path (default: None)",
    )
    args.add_argument(
        "-r",
        "--resume",
        default=None,
        type=str,
        help="path to latest checkpoint (default: None)",
    )
    args.add_argument(
        "-d",
        "--device",
        default=None,
        type=str,
        help="indices of GPUs to enable (default: all)",
    )

    # custom cli options to modify configuration from default values given in json file.
    CustomArgs = collections.namedtuple("CustomArgs", "flags type target")
    options = [
        CustomArgs(["--lr", "--learning_rate"], type=float, target="optimizer;args;lr"),
        CustomArgs(
            ["--bs", "--batch_size"], type=int, target="data_loader;args;batch_size"
        ),
    ]
    config = ConfigParser.from_args(args, options)
    main(config)