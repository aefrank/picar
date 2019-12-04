'''
Filename: my_picar_utils.py
Description: Picar utilities to help organize interfacing with the picar through the my_picar.Picar class.
Author: Andi Frank
E-mail: a2frank@eng.ucsd.edu
Purpose: CSE 276A - Intro to Robotics; Fall 2019
'''


##############################################################
#                       IMPORTS
##############################################################

import sys
from time import sleep, monotonic
from math import sin, cos, tan, atan, atan2, pi
from numpy.linalg import norm
import numpy as np
from helpers import sign, angle_a2b, within_pi, clip
from my_pid import myPID
import perspectives 
from cartesian_pose import CartesianPose
from bicycle_model import BicyclePose, BicycleModel

# Find SunFounder_PiCar submodule
sys.path.append("../lib/SunFounder_PiCar")


class PicarHardwareInterface():
    '''
    Handle low level interfacing with hardware via SunFounder_PiCar picar.front_wheels.Front_Wheels
    and picar.back_wheels.Back_Wheels classes (or their virtual_wheels analogs).
    '''

    def __init__(self, configfile="config", virtual=False, virtual_verbose=False, max_turn=40):
         # Use virtual libraries if requested (so we don't get GPIO errors for not running on a Pi)
        if not virtual:
            import picar
            from picar.front_wheels import Front_Wheels
            from picar.back_wheels import Back_Wheels
            picar.setup()
            self._fw = Front_Wheels(db=configfile)
            self._bw = Back_Wheels(db=configfile)
        else:
            from virtual_wheels import Virtual_Front_Wheels as Front_Wheels
            from virtual_wheels import Virtual_Back_Wheels as Back_Wheels
            self._fw = Front_Wheels(db=configfile, verbose=virtual_verbose)
            self._bw = Back_Wheels(db=configfile, verbose=virtual_verbose)

        # Max turn radius
        self._fw.max_turn = max_turn
        self._fw.ready()
        self._bw.ready()
        self._bw.forward()

    def turn_wheels(self, steer):
        '''
        Input steer_angle in degrees.

        Make it so inputs steer_angles are relative to 0 degrees being straight forward.
        '''
        self._fw.turn(steer + self._fw._straight_angle)

    def turn_wheels_straight(self, overshoot=10, delay=0.05):
        '''
        Often when "turning straight", the picar stops a bit short of fully straight
        forward. This is my attempt to remedy that by overshooting then correcting.

        Tune the overshoot [deg] and delay [sec] if it's too jittery.
        '''
        self.turn_wheels(overshoot)
        sleep(delay)
        self.turn_wheels(-overshoot)
        sleep(delay)
        self._fw.turn_straight()
        self._steering = 0

    def stop_motors(self):
        '''
        Low level, minimal latency method to stop picar motors. Leaves steering/direction as is.
        '''
        self._bw.stop()
        self._speed= 0

    def apply_controls(self, speed, steer, direction=1):
        '''
        Send current speed and steer_angle control signals to hardware.
        Note: direction=-1 will flip BOTH STEER AND SPEED INPUTS such that
                the steering is opposite, and the car will move in the desired direction
                THIS MIGHT NOT BE WISE but i think it is. COULD BE A BUG LOOK HERE IF 
                TURN DIRECTION IS MESSED UP WHEN BACKWARDS.
        '''
        # Capture current control values
        steer_angle = direction*int(steer) # reverse turn direction if we are going backward
        speed = int(abs(speed))

        # Set back wheel direction
        if direction == 1:
            self._bw.forward()
        elif direction == -1:
            self._bw.backward()
        elif direction == 0:
            # If direction is 0, don't change _bw's settings.
            pass
        else:
            # If any other edge case, halt picar
            self.halt()
            print('Picar object has invalid direction field {}. Picar halting.'.format(self._direction))

        # Set picar steering angle
        if steer==0:
            self.turn_wheels_straight()
        else:
            self.turn_wheels(steer)

        # Set picar speed
        if speed==0:
            self.stop_motors()
        else: 
            self._bw.speed = speed

def test_PicarHardwareInterface():
    '''
    Test PicarHardwareInterface constructor and methods
    '''
    hw = PicarHardwareInterface(virtual=True)
    hw.turn_wheels(-20)
    hw.turn_wheels_straight()
    hw.stop_motors()
    hw.apply_controls(1,-1,1)

class MyPicarController():
    '''
    Basic PID control for Picar speed and steering angle based on a BicycleModel.bicycle_model representation
    of the relative goal pose.
    '''
    def __init__(self, rho_controller=None, alpha_controller=None, beta_controller=None,
                        kpr=1, kpa=0, kpb=0, kdr=0, kda=0, kdb=0, kir=0, kia=0, kib=0):
        if rho_controller is None:
            rho_controller   = myPID(Kp=kpr, Ki=kir, Kd=kdr)
        if alpha_controller is None:
            alpha_controller = myPID(Kp=kpa, Ki=kia, Kd=kda)
        if beta_controller is None:
            beta_controller  = myPID(Kp=kpb, Ki=kib, Kd=kdb)      

        self.rho_controller   = rho_controller
        self.alpha_controller = alpha_controller
        self.beta_controller  = beta_controller

    def SPEED(self, rho, dt=1):
        return self.rho_controller.input(rho, dt=dt)

    def STEER(self, speed, alpha, beta, L, dt=1): 
        '''
        Note: Returns steer direction assuming only forward motion is possible.
        '''
        a = self.alpha_controller.input(alpha, dt=dt) 
        b = self.beta_controller .input(beta,  dt=dt)  

        # Weighted change in gamma = desired dh
        dh = a + b

        # Steer angle is measured from the front wheel, not the back wheel; 
        s = abs(speed) # make sure we have unsigned speed; direction should be handled separately
        steer = atan(dh*L/s)

        # Bound between [-pi, pi]
        return within_pi(steer)

    def DIRECTION(self, alpha, dt=1):
        # If alpha is greater than pi/2, it's easier to go backward
        # Inspired by code.py example from Homework 1.
        # https://d1b10bmlvqabco.cloudfront.net/attach/k0uju462t062l4/j12evy3w52o5kl/k1vnoghb1697/code.pdf
        if abs(alpha) > (pi/2 + 1e-4):
            return True
        else:
            return False

def test_MyPicarController():
    pc = MyPicarController()
    pc = MyPicarController(rho_controller=myPID(1,2,3))
    s = pc.SPEED(rho=4.2)
    pc.STEER(speed=s, alpha=pi/2, beta=-pi/4, L=2)
    pc.DIRECTION(alpha=pi/2)



class PicarUnitConverter():
    '''
    Handle conversions between world units and picar units. ASSUMES LINEAR RELATIONSHIPS.
    '''
    def __init__(self, speed_slope, angle_slope, time_slope=1, speed_intercept=0, angle_intercept=0):
        '''
        World = m*Picar + b
        '''
        self.world_speed_scale  = speed_slope       # [picar_time_unit/picar_length_unit * m/s] (i.e. (world speed units)/(picar speed units))
        self.world_angle_scale  = angle_slope       # [deg/picar_angle_unit]
        self.world_time_scale   = time_slope        # [sec/picar_time_unit]     (most likely picar_time_unit will be sec)
        self.world_speed_offset = speed_intercept   # [m/s]
        self.world_angle_offset = angle_intercept   # [deg]


    def speed_picar2world(self, picar_speed):
        return self.world_speed_scale*picar_speed + self.world_speed_offset     # [m/s]

    def angle_picar2world(self, picar_angle):
        return self.world_angle_scale*picar_angle + self.world_angle_offset     # [deg]

    def time_picar2world(self, picar_time):
        return self.world_time_scale*picar_time     # [sec]

    def length_picar2world(self, picar_length):     # [m]
        '''
        [world length units]    = [world speed units]                 *      [world_time_units]
                                = speed_picar2world(picar_speed)      *      time_picar2world(1)
                                = speed_picar2world(picar_length/1)   *      time_picar2world(1)
                                = speed_picar2world(picar_length)     *      self.time_scale
        '''
        return speed_picar2world(picar_length) * self.time_scale


    def speed_world2picar(self, world_speed):
        return (world_speed - self.world_speed_offset)/self.world_speed_scale   # [picar speed units] 
                                                                                # (i.e. [picar length units/picar time units])
     
    def angle_world2picar(self, world_angle):
        return (world_angle - self.world_angle_offset)/self.world_angle_scale   # [picar angle units] 

    def time_world2picar(self, world_time):
        return world_time/self.world_time_scale                                 # [picar time units]

    def length_world2picar(self, world_length):
        return speed_world2picar(world_length) / self.time_scale                # [picar length units]

    
    # @TODO: Pose transformations




def main():
    # test_PicarHardwareInterface()
    test_MyPicarController()


if __name__ == "__main__":
    main()