#!/usr/bin/python3

import logging
import argparse
from time import time

import toml
import numpy as np

from data.readers.knowledge_graph import KnowledgeGraph
from data.utils import is_readable, is_writable
from data.readers import tar
#from data.writers import tsv
from embeddings import graph_structure
from tasks.node_classification import build_dataset, build_model
from tasks.utils import create_splits, sample_mask, strip_graph

def run(args, config):
    if args.input is None:
        logging.info("No tarball supplied - building task prequisites")
        with KnowledgeGraph(path=config['graph']['file']) as kg:
            targets = strip_graph(kg, config)
            A = graph_structure.generate(kg, config)
            X, Y, X_node_map = build_dataset(kg, targets, config)
    else:
        assert is_readable(args.input)
        logging.info("Importing prepared tarball")
        A, X, Y, X_node_map = tar.read(args.input)

    # compile model computation graph
    model = build_model(X, Y, A, config)

    # create splits
    dataset = create_splits(X, Y, X_node_map, 
                            dataset_ratio = config['task']['dataset_ratio'],
                            seed = config['task']['seed'])

    train_mask = sample_mask(dataset['train']['X_idx'], Y.shape[0])

    # train model
    Y_hat = None
    nepoch = config['model']['epoch']
    batch_size = X.shape[0]  # number of nodes

    logging.info("Training for {} epoch".format(nepoch))
    for epoch in range(1, nepoch+1):
        # Log wall-clock time
        t = time()

        # Single training iteration
        model.fit([X] + A, dataset['train']['Y'], sample_weight=train_mask,
                  batch_size=batch_size, nb_epoch=1, shuffle=False, verbose=0)

        # output progress
        if epoch % 1 == 0:
            # Predict on full dataset
            Y_hat = model.predict([X] + A, batch_size=batch_size)

            # Train / validation scores
            train_val_loss, train_val_acc = evaluate_preds(Y_hat,
                                                           [dataset['train']['Y'],
                                                            dataset['val']['Y']],
                                                           [dataset['train']['X_idx'],
                                                            dataset['val']['X_idx']])

            print("Epoch: {:04d}".format(epoch),
                  "train_loss= {:.4f}".format(train_val_loss[0]),
                  "train_acc= {:.4f}".format(train_val_acc[0]),
                  "val_loss= {:.4f}".format(train_val_loss[1]),
                  "val_acc= {:.4f}".format(train_val_acc[1]),
                  "time= {:.4f}".format(time() - t))

        else:
            print("Epoch: {:04d}".format(epoch),
                  "time= {:.4f}".format(time() - t))

    # Test
    test_loss, test_acc = evaluate_preds(Y_hat, [dataset['test']['Y']], 
                                         [dataset['test']['X_idx']])
    print("Test set results:",
          "loss= {:.4f}".format(test_loss[0]),
          "accuracy= {:.4f}".format(test_acc[0]))
    
def categorical_crossentropy(preds, labels):
    return np.mean(-np.log(np.extract(labels, preds)))

def accuracy(preds, labels):
    return np.mean(np.equal(np.argmax(labels, 1), np.argmax(preds, 1)))


def evaluate_preds(preds, labels, indices):

    split_loss = list()
    split_acc = list()

    for y_split, idx_split in zip(labels, indices):
        split_loss.append(categorical_crossentropy(preds[idx_split], y_split[idx_split]))
        split_acc.append(accuracy(preds[idx_split], y_split[idx_split]))

    return split_loss, split_acc


def print_header():
    print("Multimodal Relational Graph Convolution Network")

def set_logging(args, timestamp):
    log_path = args.log_directory
    if not is_writable(log_path):
        return

    filename = "{}{}.log".format(log_path, timestamp) if log_path.endswith("/") \
                    else "{}/{}.log".format(log_path, timestamp)

    logging.basicConfig(filename=filename,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        level=logging.INFO)

    if args.verbose:
        logging.getLogger().addHandler(logging.StreamHandler())

if __name__ == "__main__":
    timestamp = int(time())

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="Configuration file (toml)", default=None)
    parser.add_argument("-i", "--input", help="Prepared input file (tar)", default=None)
    parser.add_argument("-o", "--output", help="Output file (tsv)", default=None)
    parser.add_argument("-v", "--verbose", help="Increase output verbosity", action="store_true")
    parser.add_argument("--log_directory", help="Where to save the log file", default="../log/")
    args = parser.parse_args()

    assert is_readable(args.config)
    config = toml.load(args.config)

    if args.output is None:
        args.output = './' + config['name'] + '{}.tsv'.format(timestamp)
    assert is_writable(args.output)

    set_logging(args, timestamp)
    logger = logging.getLogger(__name__)
    logger.info("Arguments:\n{}".format(
        "\n".join(["\t{}: {}".format(arg, getattr(args, arg)) for arg in vars(args)])))

    # write results
    run(args, config)
    #tsv.write(args.output, run(args, config))
    
    logging.shutdown()