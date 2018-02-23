import os
import tensorflow as tf
from functools import reduce
import progressbar
from train.train_abc import train_abc
from utils.image_ops import tfplot_vxlab, tfplot_vxflt
from utils.tf_utils import unravel_index


class train_super_vxhit(train_abc):
    def train(self):
        self.logger.info('######## Training ########')
        tf.reset_default_graph()
        with tf.Graph().as_default(), \
                tf.device('/gpu:' + str(self.args.gpu_id)):
            frames_op, poses_op, vxhit_op = \
                self.args.model_inst.placeholder_inputs()
            is_training_tf = tf.placeholder(
                tf.bool, shape=(), name='is_training')

            global_step = tf.train.create_global_step()

            pred_op, end_points = self.args.model_inst.get_model(
                frames_op, is_training_tf,
                self.args.bn_decay, self.args.regu_scale)
            shapestr = 'input: {}'.format(frames_op.shape)
            for ends in self.args.model_inst.end_point_list:
                net = end_points[ends]
                shapestr += '\n{}: {} = ({}, {})'.format(
                    ends, net.shape,
                    net.shape[0],
                    reduce(lambda x, y: x * y, net.shape[1:])
                )
            self.args.logger.info(
                'network structure:\n{}'.format(shapestr))
            loss_l2, loss_ce, loss_reg = self.args.model_inst.get_loss(
                pred_op, poses_op, vxhit_op, end_points)
            test_op = loss_l2 + loss_ce + loss_reg
            loss_op = test_op + loss_reg
            tf.summary.scalar('loss', loss_op)
            tf.summary.scalar('loss_l2', loss_l2)
            tf.summary.scalar('loss_ce', loss_ce)
            tf.summary.scalar('loss_reg', loss_reg)

            learning_rate = self.get_learning_rate(global_step)
            tf.summary.scalar('learning_rate', learning_rate)

            optimizer = tf.train.AdamOptimizer(learning_rate)
            # train_op = optimizer.minimize(
            #     loss_op, global_step=global_step)
            from tensorflow.contrib import slim
            train_op = slim.learning.create_train_op(
                loss_op, optimizer,
                # summarize_gradients=True,
                update_ops=tf.get_collection(tf.GraphKeys.UPDATE_OPS),
                global_step=global_step)
            # from tensorflow.python.ops import control_flow_ops
            # train_op = slim.learning.create_train_op(
            #     loss_op, optimizer, global_step=global_step)
            # update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
            # if update_ops:
            #     updates = tf.group(*update_ops)
            #     loss_op = control_flow_ops.with_dependencies(
            #         [updates], loss_op)

            saver = tf.train.Saver(max_to_keep=4)

            config = tf.ConfigProto()
            config.gpu_options.allow_growth = True
            config.allow_soft_placement = True
            config.log_device_placement = False
            with tf.Session(config=config) as sess:
                model_path = self.args.model_inst.ckpt_path
                if self.args.retrain:
                    init = tf.global_variables_initializer()
                    sess.run(init)
                else:
                    saver.restore(sess, model_path)
                    self.logger.info(
                        'model restored from: {}.'.format(
                            model_path))

                summary_op = tf.summary.merge_all()
                train_writer = tf.summary.FileWriter(
                    os.path.join(self.args.log_dir_t, 'train'),
                    sess.graph)
                valid_writer = tf.summary.FileWriter(
                    os.path.join(self.args.log_dir_t, 'valid'))

                ops = {
                    'batch_frame': frames_op,
                    'batch_poses': poses_op,
                    'batch_vxhit': vxhit_op,
                    'is_training': is_training_tf,
                    'summary_op': summary_op,
                    'step': global_step,
                    'train_op': train_op,
                    'loss_op': loss_op,
                    'test_op': test_op,
                    'pred_op': pred_op
                }
                self._train_iter(
                    sess, ops, saver,
                    model_path, train_writer, valid_writer)

    def train_one_epoch(self, sess, ops, train_writer):
        """ ops: dict mapping from string to tf ops """
        batch_count = 0
        loss_sum = 0
        while True:
            batch_data = self.args.model_inst.fetch_batch()
            if batch_data is None:
                break
            feed_dict = {
                ops['batch_frame']: batch_data['batch_frame'],
                ops['batch_poses']: batch_data['batch_poses'],
                ops['batch_vxhit']: batch_data['batch_vxhit'],
                ops['is_training']: True
            }
            summary, step, _, loss_val, pred_val = sess.run(
                [ops['summary_op'], ops['step'], ops['train_op'],
                    ops['loss_op'], ops['pred_op']],
                feed_dict=feed_dict)
            loss_sum += loss_val / self.args.batch_size
            if batch_count % 10 == 0:
                self.logger.info(
                    'batch {} training loss: {}'.format(
                        batch_count, loss_val))
            if batch_count % 100 == 0:
                train_writer.add_summary(summary, step)
            batch_count += 1
        mean_loss = loss_sum / batch_count
        self.args.logger.info(
            'epoch training mean loss: {:.4f}'.format(
                mean_loss))
        return mean_loss

    def valid_one_epoch(self, sess, ops, valid_writer):
        """ ops: dict mapping from string to tf ops """
        batch_count = 0
        loss_sum = 0
        while True:
            batch_data = self.args.model_inst.fetch_batch()
            if batch_data is None:
                break
            feed_dict = {
                ops['batch_frame']: batch_data['batch_frame'],
                ops['batch_poses']: batch_data['batch_poses'],
                ops['batch_vxhit']: batch_data['batch_vxhit'],
                ops['is_training']: False
            }
            summary, step, loss_val, pred_val = sess.run(
                [ops['summary_op'], ops['step'],
                    ops['test_op'], ops['pred_op']],
                feed_dict=feed_dict)
            loss_sum += loss_val / self.args.batch_size
            if batch_count % 10 == 0:
                if 'locor' == self.args.model_inst.net_type:
                    self.args.model_inst.debug_compare(
                        pred_val, self.logger)
                # elif 'poser' == self.args.model_inst.net_type:
                #     self.args.model_inst.debug_compare(
                #         pred_val, self.logger)
                self.logger.info(
                    'batch {} validate loss: {}'.format(
                        batch_count, loss_val))
            if batch_count % 100 == 0:
                valid_writer.add_summary(summary, step)
            batch_count += 1
        mean_loss = loss_sum / batch_count
        self.args.logger.info(
            'epoch validate mean loss: {:.4f}'.format(
                mean_loss))
        return mean_loss

    def evaluate(self):
        self.logger.info('######## Evaluating ########')
        tf.reset_default_graph()
        with tf.Graph().as_default(), \
                tf.device('/gpu:' + str(self.args.gpu_id)):
            # sequential evaluate, suited for streaming
            frames_op, poses_op, vxhit_op = \
                self.args.model_inst.placeholder_inputs(1)
            is_training_tf = tf.placeholder(
                tf.bool, shape=(), name='is_training')

            pred_op, end_points = self.args.model_inst.get_model(
                frames_op, is_training_tf,
                self.args.bn_decay, self.args.regu_scale)
            loss_l2, loss_ce, loss_reg = self.args.model_inst.get_loss(
                pred_op, poses_op, vxhit_op, end_points)
            test_op = loss_l2 + loss_ce + loss_reg
            loss_op = test_op + loss_reg

            saver = tf.train.Saver()

            config = tf.ConfigProto()
            config.gpu_options.allow_growth = True
            config.allow_soft_placement = True
            config.log_device_placement = False
            with tf.Session(config=config) as sess:
                model_path = self.args.model_inst.ckpt_path
                self.logger.info(
                    'restoring model from: {} ...'.format(model_path))
                saver.restore(sess, model_path)
                self.logger.info('model restored.')

                ops = {
                    'batch_frame': frames_op,
                    'batch_poses': poses_op,
                    'batch_vxhit': vxhit_op,
                    'is_training': is_training_tf,
                    'loss_op': loss_op,
                    'test_op': test_op,
                    'pred_op': pred_op
                }

                self.args.model_inst.start_evaluate()
                self.eval_one_epoch_write(sess, ops)
                self.args.model_inst.end_evaluate(
                    self.args.data_inst, self.args)

    def eval_one_epoch_write(self, sess, ops):
        batch_count = 0
        loss_sum = 0
        num_stores = self.args.model_inst.store_size
        eval_size = 1
        timerbar = progressbar.ProgressBar(
            maxval=num_stores,
            widgets=[
                progressbar.Percentage(),
                ' ', progressbar.Bar('=', '[', ']'),
                ' ', progressbar.ETA()]
        ).start()
        while True:
            batch_data = self.args.model_inst.fetch_batch(eval_size)
            if batch_data is None:
                break
            feed_dict = {
                ops['batch_frame']: batch_data['batch_frame'],
                ops['batch_poses']: batch_data['batch_poses'],
                ops['batch_vxhit']: batch_data['batch_vxhit'],
                ops['is_training']: False
            }
            loss_val, pred_val = sess.run(
                [ops['test_op'], ops['pred_op']],
                feed_dict=feed_dict)
            self.args.model_inst.evaluate_batch(pred_val)
            loss_sum += loss_val
            batch_count += eval_size
            timerbar.update(batch_count)
        timerbar.finish()
        mean_loss = loss_sum / batch_count
        self.args.logger.info(
            'epoch evaluate mean loss: {:.4f}'.format(
                mean_loss))
        return mean_loss
