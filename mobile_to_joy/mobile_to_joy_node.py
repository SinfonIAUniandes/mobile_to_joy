#!/usr/bin/env python3
"""
Mobile to Joy Node (Watchdog & Auto-Scale Edition)
- Left half: Forward/Back/Strafe
- Right half: Rotation
- Includes a 0.2s Watchdog Timer to enforce stopping.
"""

import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from geometry_msgs.msg import Twist
from mobile_sensor_msgs.msg import TouchArray


class MobileToJoyNode(Node):
    def __init__(self):
        super().__init__('mobile_to_joy_node')
        
        # --- PARAMETERS ---
        self.declare_parameter('max_radius_pixels', 250.0)
        self.declare_parameter('publish_cmd_vel', True)
        self.declare_parameter('max_linear_vel', 0.5)
        self.declare_parameter('max_angular_vel', 1.0)
        self.declare_parameter('camera_on_left', True) 
        
        self.max_radius = self.get_parameter('max_radius_pixels').value
        self.publish_cmd_vel = self.get_parameter('publish_cmd_vel').value
        self.max_linear_vel = self.get_parameter('max_linear_vel').value
        self.max_angular_vel = self.get_parameter('max_angular_vel').value
        self.camera_on_left = self.get_parameter('camera_on_left').value
        
        # --- AUTO-SCALE VARIABLES ---
        self.is_normalized = None
        self.screen_midpoint = 1200.0 
        
        # --- STATE TRACKING ---
        self.left_touch_id = None
        self.right_touch_id = None
        
        self.left_origin = {'x': 0.0, 'y': 0.0}
        self.right_origin = {'x': 0.0, 'y': 0.0}
        
        self.left_joystick = {'x': 0.0, 'y': 0.0}
        self.right_joystick = {'x': 0.0, 'y': 0.0}
        
        # --- WATCHDOG TIMER ---
        self.last_touch_time = self.get_clock().now()
        self.watchdog_timer = self.create_timer(0.1, self.watchdog_callback)
        
        # --- ROS 2 INTERFACES ---
        self.touch_subscription = self.create_subscription(
            TouchArray, '/phone/touch', self.touch_callback, 10)
        
        self.joy_publisher = self.create_publisher(Joy, '/joy', 10)
        
        if self.publish_cmd_vel:
            self.cmd_vel_publisher = self.create_publisher(Twist, '/cmd_vel', 10)
            
        self.get_logger().info('Joystick Node Initialized! (Watchdog Active)')

    def watchdog_callback(self):
        """Forces the robot to stop if no touch data is received for 0.2 seconds."""
        time_since_last_touch = (self.get_clock().now() - self.last_touch_time).nanoseconds
        
        if time_since_last_touch > 2e8:  # 0.2 seconds in nanoseconds
            # Only publish stop if we were currently moving
            if self.left_touch_id is not None or self.right_touch_id is not None:
                self.left_touch_id = None
                self.right_touch_id = None
                self.left_joystick = {'x': 0.0, 'y': 0.0}
                self.right_joystick = {'x': 0.0, 'y': 0.0}
                self.publish_joy()
                self.get_logger().debug('Watchdog triggered: Robot stopped.')

    def translate_to_landscape(self, raw_x, raw_y):
        """Translates locked portrait hardware pixels to physical landscape pixels."""
        if self.camera_on_left:
            land_x = raw_y
            land_y = raw_x
        else:
            # Assumes standard ratio, but auto-scaling prevents this from breaking
            land_x = 2400.0 - raw_y
            land_y = 1080.0 - raw_x
        return land_x, land_y

    def touch_callback(self, msg: TouchArray) -> None:
        # Reset the watchdog timer
        self.last_touch_time = self.get_clock().now()

        # Check for explicit empty array (fingers lifted)
        if not msg.touches:
            self.left_touch_id = None
            self.right_touch_id = None
            self.left_joystick = {'x': 0.0, 'y': 0.0}
            self.right_joystick = {'x': 0.0, 'y': 0.0}
            self.publish_joy()
            return

        # --- AUTO-SCALE DETECTION ---
        # If coordinates are 0.0 to 1.0, 1200 will break the right side.
        if self.is_normalized is None:
            if msg.touches[0].x <= 2.0 and msg.touches[0].y <= 2.0:
                self.is_normalized = True
                self.screen_midpoint = 0.5
                self.max_radius = 0.2  # 20% of screen
                self.get_logger().info('Auto-detected Normalized Coordinates (0.0 - 1.0)')
            else:
                self.is_normalized = False
                self.screen_midpoint = 1200.0 # Assumes standard Note 13 pixels
                self.max_radius = self.get_parameter('max_radius_pixels').value
                self.get_logger().info('Auto-detected Raw Pixel Coordinates')

        current_ids = {touch.id for touch in msg.touches}
        
        # Handle individual finger liftoffs
        if self.left_touch_id is not None and self.left_touch_id not in current_ids:
            self.left_touch_id = None
            self.left_joystick = {'x': 0.0, 'y': 0.0}
            
        if self.right_touch_id is not None and self.right_touch_id not in current_ids:
            self.right_touch_id = None
            self.right_joystick = {'x': 0.0, 'y': 0.0}

        # Process active touches
        for touch in msg.touches:
            land_x, land_y = self.translate_to_landscape(touch.x, touch.y)
            
            # Assign brand new fingers to Left or Right side
            if touch.id != self.left_touch_id and touch.id != self.right_touch_id:
                if land_x < self.screen_midpoint and self.left_touch_id is None:
                    self.left_touch_id = touch.id
                    self.left_origin = {'x': land_x, 'y': land_y} 
                
                elif land_x >= self.screen_midpoint and self.right_touch_id is None:
                    self.right_touch_id = touch.id
                    self.right_origin = {'x': land_x, 'y': land_y} 

            # Update joysticks
            if touch.id == self.left_touch_id:
                self.calculate_joystick(land_x, land_y, self.left_origin, self.left_joystick)
                
            elif touch.id == self.right_touch_id:
                self.calculate_joystick(land_x, land_y, self.right_origin, self.right_joystick)

        self.publish_joy()

    def calculate_joystick(self, current_x, current_y, origin, target_joystick):
        """Calculates distance from origin and maps to standard ROS conventions."""
        dx = current_x - origin['x']
        dy = current_y - origin['y']
        
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance > 0:
            magnitude = min(1.0, distance / self.max_radius)
            
            # X-AXIS (Strafing / Rotation): Inverted so sliding Right is negative
            target_joystick['x'] = -(dx / distance) * magnitude
            
            # Y-AXIS (Forward/Back): FIXED! Removed the negative sign. 
            # Sliding physical Up now properly outputs a positive Y value.
            target_joystick['y'] = (dy / distance) * magnitude
        else:
            target_joystick['x'] = 0.0
            target_joystick['y'] = 0.0

    def publish_joy(self) -> None:
        """Publish Joy and Twist messages."""
        joy_msg = Joy()
        joy_msg.axes = [
            self.left_joystick['x'],
            self.left_joystick['y'],
            0.0,
            self.right_joystick['x'],
            self.right_joystick['y'],
            0.0,
        ]
        joy_msg.buttons = []
        self.joy_publisher.publish(joy_msg)
        
        if self.publish_cmd_vel:
            twist_msg = Twist()
            
            # LEFT JOYSTICK: Forward/Back/Strafe
            twist_msg.linear.x = self.left_joystick['y'] * self.max_linear_vel
            twist_msg.linear.y = self.left_joystick['x'] * self.max_linear_vel
            
            # RIGHT JOYSTICK: Rotation
            twist_msg.angular.z = self.right_joystick['x'] * self.max_angular_vel
            
            self.cmd_vel_publisher.publish(twist_msg)


def main(args=None):
    rclpy.init(args=args)
    node = MobileToJoyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()