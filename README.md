# mobile_to_joy

A ROS 2 Jazzy node that translates smartphone touch screen input into standard `sensor_msgs/Joy` and `geometry_msgs/Twist` messages for robot control.

## Overview

This package converts raw multi-touch coordinates from a mobile device screen into dual-joystick control signals. The screen is divided into two regions:

- **Left Half**: XY movement joystick (forward/back/strafe)
- **Right Half**: Rotation joystick (yaw control)

The node includes intelligent auto-scaling to handle both normalized (0.0–1.0) and raw pixel coordinates, orientation translation for landscape mode, and a safety watchdog timer to ensure the robot stops if communication is lost.

## Features

- **Virtual Twin Joysticks**: Left half controls translational motion, right half controls rotation
- **Auto-Scaling**: Automatically detects whether coordinates are normalized (0.0–1.0) or raw pixels
- **Orientation Translation**: Converts locked portrait hardware coordinates to landscape coordinates
- **Configurable Camera Position**: Supports camera on left or right side of device
- **Dual Output**: Publishes both `Joy` (for game controller emulation) and `Twist` (for direct velocity control)
- **Watchdog Safety Timer**: Forces robot stop if no touch data received for 0.2 seconds
- **Per-Finger Tracking**: Each joystick independently tracks a single finger ID
- **Graceful Liftoff Handling**: When one finger lifts, only that joystick resets; the other continues

## Installation

### Dependencies

```bash
sudo apt install ros-jazzy-sensor-msgs ros-jazzy-geometry-msgs
```

### Build

```bash
cd ~/ros2_ws
colcon build --packages-select mobile_to_joy
source install/setup.bash
```

## Running the Node

### Basic Usage

```bash
ros2 run mobile_to_joy mobile_to_joy_node
```

### With Custom Parameters

```bash
ros2 run mobile_to_joy mobile_to_joy_node --ros-args \
  -p max_radius_pixels:=200.0 \
  -p max_linear_vel:=1.0 \
  -p max_angular_vel:=1.5 \
  -p camera_on_left:=false
```

### With Launch File (Optional)

Create a launch file `launch/mobile_to_joy.launch.py`:

```python
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='mobile_to_joy',
            executable='mobile_to_joy_node',
            name='mobile_to_joy',
            parameters=[
                {'max_radius_pixels': 250.0},
                {'publish_cmd_vel': True},
                {'max_linear_vel': 0.5},
                {'max_angular_vel': 1.0},
                {'camera_on_left': True},
            ],
            output='screen',
        ),
    ])
```

Then launch with:
```bash
ros2 launch mobile_to_joy mobile_to_joy.launch.py
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_radius_pixels` | float | `250.0` | Pixel distance from joystick center required to reach max output (1.0). Auto-scales to 0.2 if normalized coords detected. |
| `publish_cmd_vel` | bool | `true` | If true, publishes `Twist` messages to `/cmd_vel`; if false, only publishes `Joy`. |
| `max_linear_vel` | float | `0.5` | Maximum linear velocity (m/s) for `Twist.linear.{x,y}`. |
| `max_angular_vel` | float | `1.0` | Maximum angular velocity (rad/s) for `Twist.angular.z`. |
| `camera_on_left` | bool | `true` | Orientation of device camera. If true, portrait-to-landscape translation assumes camera on left edge. |

## Subscriptions

| Topic | Message Type | Description |
|-------|--------------|-------------|
| `/phone/touch` | `mobile_sensor_msgs/TouchArray` | Raw touch screen input from mobile device |

### TouchArray Message Structure

```
std_msgs/Header header
TouchPoint[] touches

# Each TouchPoint:
uint32 id           # Unique finger ID
float32 x           # X coordinate (0.0–1.0 normalized or raw pixels)
float32 y           # Y coordinate (0.0–1.0 normalized or raw pixels)
float32 pressure    # Touch pressure (0.0–1.0)
float32 major_axis  # Contact area major axis
```

## Publications

| Topic | Message Type | Description |
|-------|--------------|-------------|
| `/joy` | `sensor_msgs/Joy` | Standard gamepad joy message (6 axes, no buttons) |
| `/cmd_vel` | `geometry_msgs/Twist` | Robot velocity command (if `publish_cmd_vel=true`) |

### Joy Message Format

```
axes[0] = Left Joystick X   (strafing: -1.0 left, +1.0 right)
axes[1] = Left Joystick Y   (forward: -1.0 back, +1.0 forward)
axes[2] = 0.0               (unused)
axes[3] = Right Joystick X  (rotation: -1.0 left, +1.0 right)
axes[4] = Right Joystick Y  (unused)
axes[5] = 0.0               (unused)
buttons  = []               (no buttons)
```

### Twist Message Mapping

```
linear.x  = left_joystick.y * max_linear_vel      (forward/backward)
linear.y  = left_joystick.x * max_linear_vel      (strafing)
linear.z  = 0.0
angular.x = 0.0
angular.y = 0.0
angular.z = right_joystick.x * max_angular_vel   (rotation)
```

## Touch Control Layout

```
┌─────────────────────────────────────┐
│                                     │
│   LEFT HALF                RIGHT    │
│   (Motion XY)              (Rotate) │
│                                     │
│   ↑                                 │
│ ← ⊗ →          (1200px midpoint)    │
│   ↓                                 │
│                                     │
│   Origin at screen center           │
│   Radius: max_radius_pixels         │
│                                     │
└─────────────────────────────────────┘
```

## How It Works

1. **Touch Detection**: Device sends touch coordinates via `/phone/touch`
2. **Auto-Scale Detection**: Node detects coordinate system (normalized vs. raw pixels)
3. **Landscape Translation**: Converts portrait hardware coordinates to landscape space
4. **Region Assignment**: New touches are assigned to left (motion) or right (rotation) joystick
5. **Distance Calculation**: Finger distance from joystick center is mapped to -1.0 to +1.0 output
6. **Publication**: Joy and Twist messages are published immediately
7. **Watchdog Safety**: If no touch for 0.2 seconds, robot is commanded to stop

## Troubleshooting

### Node starts but no output

- **Check subscription**: `ros2 topic echo /phone/touch`
- **Verify mobile app**: Ensure device is sending touches to `/phone/touch`
- **Check parameters**: `ros2 param list /mobile_to_joy_node`

### Joystick feels backwards or inverted

- Adjust **axis signs** in `calculate_joystick()` method
- Check `camera_on_left` parameter (set to `false` if camera is on right edge)
- Verify mobile app coordinate convention

### Robot jerks or stops unexpectedly

- **Watchdog timeout**: Ensure mobile device sends touches at least every 0.15 seconds
- **Message parsing error**: Check that `TouchArray` message type matches publisher
- **Network latency**: May require tuning watchdog threshold (edit `watchdog_callback()`)

### Coordinates don't scale correctly

- Node auto-detects coordinate system on first touch
- If detection fails, check raw coordinate values: `ros2 topic echo --field touches /phone/touch`
- Force normalization by ensuring mobile app outputs 0.0–1.0 values

## Example Usage with Nav2

To use with a differential-drive robot:

```bash
# Terminal 1: Start mobile node
ros2 run mobile_to_joy mobile_to_joy_node

# Terminal 2: Use Joy-to-Twist adapter (if needed)
ros2 run teleop_twist_joy teleop_node --ros-args -r /cmd_vel:=/base_controller/cmd_vel

# Or directly use /cmd_vel published by mobile_to_joy
ros2 run robot_control drive_node
```

## Author

Created for ROS 2 Jazzy  
University of the Andes, Bogotá  
Contact: sinfonia@uniandes.edu.co

## License

MIT License (or your preferred license)

---

**Last Updated**: May 7, 2026
