# MICROSERVICE SPEC: VITAMIN D CALCULATOR

## PURPOSE
Purpose is to output the time-windows for the day when user must stay under the sun in order to produce Vitamin D effectively for their skin type.
new requirements: show all radiation types per day, and windows when user should avoid sun radiation because it doesn't offer any benefits. when does it offer benefits?

## DOMAIN KNOWLEDGE
Exposure is influenced by the following factors:
- skin type: darker skin's require more minutes in the sun
- skin exposure: the more clothes the person wears, the less skin is available to produce vitamin D.
- sun's height at the sky, which is calculated by knowing:
-- current location's longitude and latitude
-- current date
- how many clouds or other weather phenomena interrupt the direct sunlight

## OUTPUTS:
- The number of minutes the person should stay under the sun and between which hours. Answer template "You should stay under the sun for X minutes between Y and Z hours of the day"

## INPUTS:
- current users location, either manually or automatically retrieved by their device. If manually, create another microservice run to calculate the actual location's latitude and longitude called 'location-details-extractor'
- weather forecast of the remaining day for this location, by hitting the free api "https://api.open-meteo.com/v1/forecast", which we will call from now on 'open-meteo'
- current date, retrieve automatically

## PROCESSING:
- Takes the current user location and date and makes the proper call to the 'open-meteo' api, in order to get back the weather forecast related to clouds, rain and other phenomena that might interrupt direct sunlight from reaching the person. Thus it should add the corresponding parameters in the api call based on the api's documentation.
- Takes weather forecast, date and exact location and calculates the available time window for vitamin D exposure
- Takes into account person's skin type and clothing density, and calculates how many minutes into that window the person should stay to have maximum production for the day
- Returns the result in a gui text box and also in a chart where the X-axis = hour of the day (so 24 points) and Y-axis = minutes of exposure for optimal result.

## USER INTERFACE DETAILS:
- It should use a GUI where user inputs the location, skin type and clothing density.
- GUI should have happy, bright colors that signal health, well-being and longevity. Inputs widgets should be placed on the left side, while output should be placed on the right side, the graph on top and written text at the bottom.
- GUI should be served at '/' so it will be the landing page, and the only page actually.
- Skin type is a dropdown menu with the following options = {I, II, III, IV, V} with I being super white and V deep african black.
- Clothing density is a dropdown menu with the following options = {naked, swimsuit, summer clothes, winter clothes}, which correspond approximately to the following exposures of skin {100%, 85%, 30%, 5%}.
- Location is a drop down menu with the three biggest cities of each country in the world as options (you should locate them as part of this development and serve them ready) or the option to identify automatically. The automatic identification option should be placed first. In that case, you should leverage browser cookies or other publicly available information to get the user's location exactly.

## ENDPOINT DESCRIPTION:
- '/': landing page that contains also the only GUI, as described above in detail
- 'POST /process': accepts the inputs as json calls the microservice logic to calculate vitaminD exposure
- '/health': health endpoint that behaves as usual - if everything is ok then it has a text that says {status: ok}, if not it returns {status: DOWN} when possible. 
- '/metrics': exposes application metrics
- any other endpoints that you believe might be needed for the smooth implementation of the business logic.



