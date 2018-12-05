import os
from collections import namedtuple
import numpy as np
from collections import deque
from copy import deepcopy
import matplotlib.pyplot as mpplot
from matplotlib.animation import FuncAnimation
import tensorflow as tf
# from tensorflow.contrib import slim
from colour import Color
import time
# from multiprocessing import Queue, Pool
from args_holder import args_holder
from utils.iso_boxes import iso_cube
from camera.hand_finder import hand_finder


class capture:
    class caminfo_ir:
        image_size = (480, 640)
        region_size = 120
        crop_size = 128  # input image size to models (may changed)
        crop_range = 480  # only operate within this range
        z_range = (100., 1060.)
        anchor_num = 8
        # intrinsic paramters of Intel Realsense SR300
        focal = (463.889, 463.889)
        centre = (320, 240)
        # joints description
        join_name = [
            'Wrist',
            'TMCP', 'IMCP', 'MMCP', 'RMCP', 'PMCP',
            'TPIP', 'TDIP', 'TTIP',
            'IPIP', 'IDIP', 'ITIP',
            'MPIP', 'MDIP', 'MTIP',
            'RPIP', 'RDIP', 'RTIP',
            'PPIP', 'PDIP', 'PTIP'
        ]
        join_num = 21
        join_type = ('W', 'T', 'I', 'M', 'R', 'P')
        join_color = (
            # Color('cyan'),
            Color('black'),
            Color('magenta'),
            Color('blue'),
            Color('lime'),
            Color('yellow'),
            Color('red')
        )
        join_id = (
            (1, 6, 7, 8),
            (2, 9, 10, 11),
            (3, 12, 13, 14),
            (4, 15, 16, 17),
            (5, 18, 19, 20)
        )
        bone_id = (
            ((0, 1), (1, 6), (6, 11), (11, 16)),
            ((0, 2), (2, 7), (7, 12), (12, 17)),
            ((0, 3), (3, 8), (8, 13), (13, 18)),
            ((0, 4), (4, 9), (9, 14), (14, 19)),
            ((0, 5), (5, 10), (10, 15), (15, 20))
        )
        bbox_color = Color('orange')

        def __init__():
            pass

    # helper to define the rendering canvas
    Canvas = namedtuple("Canvas", "fig ims axes")

    def create_canvas(self):
        # Create the figure canvas
        fig, _ = mpplot.subplots(nrows=1, ncols=2, figsize=(2 * 6, 1 * 6))
        ax1 = mpplot.subplot(1, 2, 1)
        # ax1.set_axis_off()
        ax1.set_xlim(0, 640)
        ax1.set_ylim(480, 0)
        ax2 = mpplot.subplot(1, 2, 2)
        # ax3 = mpplot.subplot(1, 3, 3)
        # ax2.set_axis_off()
        # mpplot.subplots_adjust(left=0, right=1, top=1, bottom=0)
        im1 = ax1.imshow(
            np.zeros(self.caminfo.image_size, dtype=np.float),
            vmin=0., vmax=1., cmap=mpplot.cm.bone_r)
        im2 = ax2.imshow(np.zeros([480, 640, 3], dtype=np.uint8))
        # im3 = ax3.imshow(
        #     np.zeros((128, 128), dtype=np.float),
        #     vmin=0., vmax=1., cmap=mpplot.cm.bone_r)
        mpplot.tight_layout()
        canvas = self.Canvas(
            fig=fig, ims=(im1, im2), axes=(ax1, ax2))
        return canvas

    def create_debug_canvas(self):
        # Create the figure canvas
        fig, _ = mpplot.subplots(nrows=1, ncols=3, figsize=(3 * 4, 1 * 4))
        ax1 = mpplot.subplot(1, 3, 1)
        ax2 = mpplot.subplot(1, 3, 2)
        ax3 = mpplot.subplot(1, 3, 3)
        im1 = ax1.imshow(
            np.zeros((128, 128), dtype=np.float),
            vmin=0., vmax=1., cmap=mpplot.cm.bone_r)
        im2 = ax2.imshow(
            np.zeros((128, 128), dtype=np.float),
            vmin=0., vmax=1., cmap=mpplot.cm.bone_r)
        im3 = ax3.imshow(
            np.zeros((128, 128), dtype=np.float),
            vmin=0., vmax=1., cmap=mpplot.cm.bone_r)
        mpplot.tight_layout()
        canvas = self.Canvas(
            fig=fig, ims=(im1, im2, im3), axes=(ax1, ax2, ax3))
        return canvas

    def show_debug_fig(self, img, cube):
        points3_pick = cube.pick(
            self.args.data_ops.img_to_raw(img, self.caminfo))
        points3_norm = cube.transform_center_shrink(points3_pick)
        # print(points3_pick.shape, points3_norm.shape)
        coord, depth = cube.project_ortho(points3_norm, roll=0)
        img_crop = cube.print_image(coord, depth, self.caminfo.crop_size)
        self.debug_fig.ims[0].set_data(img_crop)
        coord, depth = cube.project_ortho(points3_norm, roll=1)
        img_crop = cube.print_image(coord, depth, self.caminfo.crop_size)
        self.debug_fig.ims[1].set_data(img_crop)
        coord, depth = cube.project_ortho(points3_norm, roll=2)
        img_crop = cube.print_image(coord, depth, self.caminfo.crop_size)
        self.debug_fig.ims[2].set_data(img_crop)

    def __init__(self, args):
        self.args = args
        self.caminfo = self.caminfo_ir
        # self.caminfo = args.data_inst  # TEST!!
        # self.debug_fig = False
        self.debug_fig = True

        # create the rendering canvas
        def close(event):
            if event.key == 'q':
                mpplot.close(event.canvas.figure)
            if event.key == 'b':
                mpplot.savefig(os.path.join(
                    self.args.out_dir,
                    'capture_{}.png'.format(time.time())))

        self.canvas = self.create_canvas()
        self.canvas.fig.canvas.mpl_connect(
            "key_press_event", close)
        if self.debug_fig:
            self.debug_fig = self.create_debug_canvas()

    def show_results(
        self, canvas,
            cube=iso_cube(np.array([-200, 20, 400]), 120),
            pose_det=None):
        ax = canvas.axes[0]
        rects = cube.proj_rects_3(
            self.args.data_ops.raw_to_2d,
            self.caminfo
        )
        colors = [Color('orange').rgb, Color('red').rgb, Color('lime').rgb]
        for ii, rect in enumerate(rects):
            rect.draw(ax, colors[ii])
        if pose_det is None:
            return
        self.args.data_draw.draw_pose2d(
            ax, self.caminfo,
            self.args.data_ops.raw_to_2d(pose_det, self.caminfo)
        )

    def detect_region(self, depth, cube, sess, ops):
        depth_prow = self.args.model_inst.prow_one(
            depth, cube, self.args, self.caminfo)
        depth_prow = np.expand_dims(depth_prow, -1)
        depth_prow = np.expand_dims(depth_prow, 0)
        feed_dict = {
            ops['batch_frame']: depth_prow,
            ops['is_training']: False
        }
        pred_val = sess.run(
            ops['pred'],
            feed_dict=feed_dict)
        pose_det = self.args.model_inst.rece_one(
            pred_val, cube, self.caminfo)
        return pose_det

    def show_detection(self, cam, sess, ops):
        hfinder = hand_finder(self.args, self.caminfo)

        def update(i):
            canvas = self.canvas
            ax = canvas.axes[0]
            [p.remove() for p in reversed(ax.patches)]  # remove previews Rectangle drawings
            for artist in ax.lines + ax.collections:
                artist.remove()  # remove all lines
            camframes = cam.provide()
            depth_image = camframes.depth
            color_image = camframes.color
            canvas.ims[0].set_data(
                depth_image / self.caminfo.z_range[1])
            canvas.ims[1].set_data(color_image)
            cube = hfinder.simp_crop(depth_image)
            if cube is False:
                return
            # cube = camframes.extra  # FetchHands17
            pose_det = self.detect_region(
                depth_image, cube, sess, ops)
            self.show_results(canvas, cube, pose_det)
            self.show_debug_fig(depth_image, cube)

        # assign return value is necessary! Otherwise no updates.
        anim = FuncAnimation(
            self.canvas.fig, update, blit=False, interval=1)
        if self.debug_fig:
            anim_debug = FuncAnimation(
                self.debug_fig.fig, update, blit=False, interval=1)
        mpplot.show()

    def capture_detect(self, cam):
        tf.reset_default_graph()
        with tf.Graph().as_default(), \
                tf.device('/gpu:' + str(self.args.gpu_id)):
            placeholders = \
                self.args.model_inst.placeholder_inputs(1)
            frames_op = placeholders.frames_tf
            is_training_tf = tf.placeholder(
                tf.bool, shape=(), name='is_training')
            pred_op, end_points = self.args.model_inst.get_model(
                frames_op, is_training_tf,
                self.args.bn_decay, self.args.regu_scale)
            saver = tf.train.Saver()
            config = tf.ConfigProto()
            config.gpu_options.allow_growth = True
            config.allow_soft_placement = True
            config.log_device_placement = False
            with tf.Session(config=config) as sess:
                model_path = self.args.model_inst.ckpt_path
                print('restoring model from: {} ...'.format(
                    model_path))
                saver.restore(sess, model_path)
                print('model restored.')
                ops = {
                    'batch_frame': frames_op,
                    'is_training': is_training_tf,
                    'pred': pred_op
                }
                self.show_detection(cam, sess, ops)

    def capture_test(self, cam):
        def update(i):
            canvas = self.canvas
            camframes = cam.provide()
            depth_image = camframes.depth
            color_image = camframes.color
            canvas.ims[0].set_data(
                depth_image / self.caminfo.z_range[1])
            canvas.ims[1].set_data(color_image)
            cube = iso_cube(np.array([0, 0, 400]), 120)
            # cube=iso_cube(np.array([-200, 20, 400]), 120)
            self.show_results(canvas, cube)

        # assign return value is necessary! Otherwise no updates.
        anim = FuncAnimation(
            self.canvas.fig, update, blit=False, interval=1)
        anim.save(
            os.path.join(self.args.out_dir, "capture_{}.mp4".format(time.time())),
            fps=30, extra_args=['-vcodec', 'libx264'])

    def capture_loop(self):
        # from camera.realsense_cam import FetchHands17
        # with FetchHands17(self.caminfo, self.args) as cam:
        from camera.realsense_cam import realsence_cam
        with realsence_cam(self.caminfo) as cam:
            # self.capture_test(cam)
            self.capture_detect(cam)


def test_camera(cap):
    # test the camera projection: center should align with the image dimension
    cube = iso_cube(np.array([0, 0, 400]), 120)
    rects = cube.proj_rects_3(
        cap.args.data_ops.raw_to_2d,
        cap.caminfo
    )
    np.set_printoptions(formatter={'float': '{:6.4f}'.format})
    for ii, rect in enumerate(rects):
        rect.show_dims()


if __name__ == '__main__':
    with args_holder() as argsholder:
        argsholder.parse_args()
        ARGS = argsholder.args
        ARGS.mode = 'detect'
        ARGS.model_name = 'super_edt2m'
        argsholder.create_instance()
        cap = capture(ARGS)
        test_camera(cap)
        cap.capture_loop()
