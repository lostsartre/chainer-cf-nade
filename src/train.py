import argparse
import cPickle as pickle
import glob
import numpy as np
import os
import six
import chainer
import chainer.functions as F
from chainer import cuda
from chainer import serializers
from chainer import optimizers
from trainer import CfNadeTrainer
from net import CfNade

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CF-NADE')
    parser.add_argument('--gpu',           '-g', default=-1,    type=int, help='GPU ID (negative value indicates CPU)')
    parser.add_argument('--input',         '-i', default=None,  type=str, help='input model file path')
    parser.add_argument('--output',        '-o', required=True, type=str, help='output model file path')
    parser.add_argument('--data_file',     '-d', required=True, type=str, help='dataset file path')
    parser.add_argument('--batch_size',    '-b', default=512,   type=int, help='mini batch size')
    parser.add_argument('--layer_num',     '-l', default=1,     type=int, help='number of layers')
    parser.add_argument('--ordinal_weight',     default=1,     type=float, help='weight of ordinal loss')
    parser.add_argument('--iter',                default=200,   type=int, help='number of iteration')
    parser.add_argument('--save_iter',           default=10,   type=int, help='number of iteration to save model')
    parser.add_argument('--lr',                  default=1e-3,  type=float, help='learning rate')
    parser.add_argument('--weight_decay',        default=0.015, type=float, help='weight decay')
    parser.add_argument('--item_base',           action='store_true', help='item-base prediction, default is user-base')
    parser.add_argument('--random_seed',         default=1,     type=int, help="random seed")
    args = parser.parse_args()

    np.random.seed(args.random_seed)
    device_id = args.gpu
    if device_id >= 0:
        cuda.check_cuda_available()

    with open(args.data_file, 'rb') as f:
        if args.item_base:
            (item_num, user_num, train_data, test_data) = pickle.load(f)
        else:
            (user_num, item_num, train_data, test_data) = pickle.load(f)
    net = CfNade(item_num, layer_num=args.layer_num)
    optimizer = optimizers.Adam(args.lr)
    optimizer.setup(net)
    optimizer.add_hook(chainer.optimizer.WeightDecay(args.weight_decay))

    if args.item_base:
        train_items, train_users, train_ratings, train_timestamps = train_data
    else:
        train_users, train_items, train_ratings, train_timestamps = train_data

    # split train/valid/test data
    data_length = len(train_users)
    order = np.random.permutation(data_length)
    if test_data is None:
        train_num = int(data_length * 0.85)
        valid_num = int(data_length * 0.05)
        train_order, valid_order, test_order = np.split(order, [train_num, train_num + valid_num])
    else:
        train_num = int(data_length * 0.95)
        train_order, valid_order = np.split(order, [train_num])
        test_order = None
        if args.item_base:
            test_items, test_users, test_ratings, test_timestamps = test_data
        else:
            test_users, test_items, test_ratings, test_timestamps = test_data
    valid_users = train_users[valid_order]
    valid_items = train_items[valid_order]
    valid_ratings = train_ratings[valid_order]
    if test_order is not None:
        test_users = train_users[test_order]
        test_items = train_items[test_order]
        test_ratings = train_ratings[test_order]
    train_users = train_users[train_order]
    train_items = train_items[train_order]
    train_ratings = train_ratings[train_order]

    column_num = np.max(np.bincount(train_users))
    train_x = np.full((user_num, column_num), -1, dtype=np.int32)
    train_r = np.full((user_num, column_num), -1, dtype=np.int32)
    for i in six.moves.range(user_num):
        index = (train_users == i)
        length = np.sum(index)
        train_x[i,:length] = train_items[index]
        train_r[i,:length] = train_ratings[index]

    column_num = np.max(np.bincount(valid_users))
    valid_x = np.full((user_num, column_num), -1, dtype=np.int32)
    valid_r = np.full((user_num, column_num), -1, dtype=np.int32)
    for i in six.moves.range(user_num):
        index = (valid_users == i)
        length = np.sum(index)
        valid_x[i,:length] = valid_items[index]
        valid_r[i,:length] = valid_ratings[index]

    column_num = np.max(np.bincount(test_users))
    test_x = np.full((user_num, column_num), -1, dtype=np.int32)
    test_r = np.full((user_num, column_num), -1, dtype=np.int32)
    for i in six.moves.range(user_num):
        index = (test_users == i)
        length = np.sum(index)
        test_x[i,:length] = test_items[index]
        test_r[i,:length] = test_ratings[index]

    progress_state = {'valid_accuracy': 100, 'test_accuracy': 100}
    def progress_func(epoch, loss, accuracy, valid_loss, valid_accuracy, test_loss, test_accuracy):
        print 'epoch: {} done'.format(epoch)
        print('train mean loss={}, accuracy={}'.format(loss, accuracy))
        if valid_loss is not None and valid_accuracy is not None:
            print('valid mean loss={}, accuracy={}'.format(valid_loss, valid_accuracy))
        if test_loss is not None and test_accuracy is not None:
            print('test mean loss={}, accuracy={}'.format(test_loss, test_accuracy))
        if valid_accuracy < progress_state['valid_accuracy']:
            serializers.save_npz(args.output, net)
            progress_state['valid_accuracy'] = valid_accuracy
            progress_state['test_accuracy'] = test_accuracy
        if epoch % args.save_iter == 0:
            base, ext = os.path.splitext(args.output)
            serializers.save_npz('{0}_{1:04d}{2}'.format(base, epoch, ext), net)

    trainer = CfNadeTrainer(net, optimizer, args.iter, args.batch_size, device_id, ordinal_weight=args.ordinal_weight)
    trainer.fit(train_x, train_r, valid_x, valid_r, test_x, test_r, callback=progress_func)
    serializers.save_npz(args.output, net)

    print('final test accuracy={}'.format(progress_state['test_accuracy']))
