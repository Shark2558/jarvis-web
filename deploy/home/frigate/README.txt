FRIGATE FOR JARVIS - what to do in Frigate (about 10 minutes)

Frigate is the program on your laptop that watches the phone camera. Pictures and video stay on your
laptop. JARVIS only hears "a person came to the gate at 23:41".

1. Open  https://localhost:8971  in the browser on the laptop. The password is the one the setup
   script printed ("Frigate admin password").

2. Check the picture: Frigate -> Live -> gate. If you see your gate, the camera works. If not, go
   back to setup step 7 and check the phone's address, login and password.

3. Draw the two zones (Frigate -> Settings -> Masks and zones -> gate):
   - gate     : around YOUR OWN gate only. This is the alarm zone. A person walking into it is a
                burglar alert while the alarm is on.
   - doorstep : around the spot where parcels are left (only needed for parcel alerts).
   The zones in the file are tiny dots in the corner. Until you redraw them JARVIS sees nothing.

4. Keep the road and your neighbours out of it.
   Point the phone at your own gate. Use "Mask" to blank out the road, the neighbour's door and
   windows. JARVIS must not watch them. Zones and masks are your choice and can be changed any time.

5. In JARVIS -> Home -> Cameras, give the camera a name you like (for example "Front gate"). The
   zone names stay `gate` and `doorstep`.

6. Parcels (optional, setup step 12): Frigate -> Classification -> Add -> State. Name it `doorstep`,
   states `package` and `empty`, draw the box over the doorstep, then sort 10-20 example pictures of
   each. It takes a few days of real pictures to become good. Until then JARVIS says
   "Train the doorstep model on your laptop" and sends no parcel alerts.

7. At night a phone camera sees little (phones have no infrared). A light at the gate helps.

How long things are kept on your laptop: recordings and pictures of events 7 days (alerts) or 3
days (other detections); nothing is recorded all the time. You can shorten this in JARVIS -> Home.

If the laptop is asleep or off, there is no camera, no alert and no history until it is back.
This is not a monitored alarm service: a person can be missed.
