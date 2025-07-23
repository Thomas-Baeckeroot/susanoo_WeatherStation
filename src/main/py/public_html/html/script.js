console.log("---Start---");
const SIZE_LIMIT = 512000;

let hour = undefined; // :int
let minute = undefined; // :int
let firstDaylightHhMm = undefined;
let lastDaylightHhMm = undefined;
let lastHhMm = undefined;

let picturesData = {};
let picturesProperties = {};
let sortedPictures = undefined;
let index = undefined;
let selectedHhMm15 = undefined;
let selectedPicture = undefined;

async function fetchData(sensor, year, month, day) {
    console.log(".fetchData('" + sensor + "', '" + year + "', '" + month + "', '" + day + "') - start method");
    // Construct the URL with parameters for the fetch call
    let url = "/captures.json";
    let firstParam = true;
    if (sensor !== null && sensor !== 'null' && sensor !== undefined) {
        url += (firstParam ? "?s=" : "&s=") + sensor;
        firstParam = false;
    }
    if (year !== null && year !== 'null' && year !== undefined) {
        url += (firstParam ? "?y=" : "&y=") + year;
        firstParam = false;
    }
    if (month !== null && month !== 'null' && month !== undefined) {
        url += (firstParam ? "?m=" : "&m=") + month;
        firstParam = false;
    }
    if (day !== null && day !== 'null' && day !== undefined) {
        url += (firstParam ? "?d=" : "&d=") + day;
    }
    try {
        const response = await fetch(url);
        if (!response.ok) {
            // const err = `Error while getting list of pictures of sensor '${sensor}' for ISO date '${year}-${month}-${day}'! Got HTTP status '${response.status}'`;
            const err = `Error while getting list of pictures with url '${url}': received HTTP status '${response.status}'`;
            console.error(".fetchData - " + err);
            picturesData = {};
            picturesProperties = {
                "sensor": null,
                "year": null,
                "month_day": null, "error_message": err
            };
            sortedPictures = {};
			return;
        }

        const data = await response.json();
        if (data.pictures && data.picturesProperties) {
            // Update picturesData with data from capture.json
            picturesData = data.pictures;
            // Update picturesProperties with data from capture.json
            picturesProperties = data.picturesProperties;
            console.log(".fetchData() - Data updated successfully:", picturesData, picturesProperties);
            sortedPictures = Object.keys(picturesData).sort();

            console.log(".fetchData() - interpreted picturesProperties:", picturesProperties.sensor, picturesProperties.year);
        } else {
            console.error(".fetchData() - Incorrect JSON format.");
            // Set fallback data when JSON format is incorrect
            picturesData = {};
            picturesProperties = {
                "sensor": sensor || 'tilleul',
                "year": year || new Date().getFullYear(),
                "month_day": (month && day) ? String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0') : null,
                "error_message": "Incorrect JSON format from server"
            };
            sortedPictures = [];
        }
    } catch (error) {
        console.error(".fetchData() - An error occurred during the fetching of data from captures.json:", error.message);
        // Set fallback data when fetch fails
        picturesData = {};
        picturesProperties = {
            "sensor": sensor || 'tilleul',
            "year": year || new Date().getFullYear(),
            "month_day": (month && day) ? String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0') : null,
            "error_message": "Failed to fetch data: " + error.message
        };
        sortedPictures = [];
    }
}

async function handleDayChangeClick(nDays) {
    console.log(".handleDayChangeClick(" + nDays + ") - Event 'click' on element #previous|next_day");
    console.log("picturesProperties.sensor = " + picturesProperties.sensor);
    console.log("picturesProperties.year = " + picturesProperties.year);
    console.log("picturesProperties.month_day (current) = " + picturesProperties.month_day);
    // Safe against month_day null/undefined
    if (!picturesProperties.month_day) {
        console.error("picturesProperties.month_day is null or undefined");
        return;
    }
    const [month, day] = picturesProperties.month_day.split("-");
    const shiftedDate = new Date(parseInt(picturesProperties.year), parseInt(month) - 1, parseInt(day) + nDays);
    await refreshDate(picturesProperties.sensor, shiftedDate.getFullYear(), shiftedDate.getMonth() + 1, shiftedDate.getDate());
}

async function monthChange(nMonths) {
    console.log(".handleDayChangeClick(" + nMonths + ") - Event 'click' on element #previous|next_month");
    console.log("picturesProperties.sensor = " + picturesProperties.sensor);
    console.log("picturesProperties.year = " + picturesProperties.year);
    console.log("picturesProperties.month_day (current) = " + picturesProperties.month_day);
    // Safe against month_day null/undefined
    if (!picturesProperties.month_day) {
        console.error("picturesProperties.month_day is null or undefined");
        return;
    }
    const [month, day] = picturesProperties.month_day.split("-");
    const shiftedDate = new Date(parseInt(picturesProperties.year), parseInt(month) + nMonths - 1, parseInt(day));
    // todo "Next month" from date 31st/Jan. returns 3rd/March. It would be more logical to return last day of next month (February) instead.
    await refreshDate(picturesProperties.sensor, shiftedDate.getFullYear(), shiftedDate.getMonth() + 1, shiftedDate.getDate());
}

async function updateDateData() {
    console.log(".updateDateData()");

    // Fallback to current date if picturesProperties is not initialised
    if (!picturesProperties || !picturesProperties.year) {
        const now = new Date();
        picturesProperties = {
            sensor: 'tilleul', // Used as default but probability to be right is low...
            year: now.getFullYear(),
            month_day: String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0'),
            error_message: ''
        };
        console.warn("picturesProperties was not initialized, using current date as fallback");
    }

    document.getElementById("current_year").textContent = picturesProperties.year;
    if (picturesProperties.month_day) { // Safe against month_day null/undefined
        const [month, day] = picturesProperties.month_day.split("-");
        document.getElementById("current_month").textContent = month;
        document.getElementById("current_day").textContent = day;
    } else {
        // Fallback to current date
        const now = new Date();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        document.getElementById("current_month").textContent = month;
        document.getElementById("current_day").textContent = day;
        picturesProperties.month_day = month + '-' + day;
        console.warn("month_day was null, using current date as fallback");
    }
	document.getElementById("current_sensor").textContent = picturesProperties.sensor;

    //makeElementClickable(document.getElementById("previous_day"));
    //document.getElementById("previous_day").addEventListener("click", handleDayChangeClick());
}

/**
 Reset background of top picture selector for currently selected
 */
async function unselectPictureSelector() {
    console.log(".unselectPictureSelector()");
    if (selectedHhMm15 !== undefined) {
        const hh_mm_element = document.getElementById(selectedHhMm15);
        if (selectedPicture.fSize < SIZE_LIMIT) {
            hh_mm_element.classList.remove("night-selected");
            hh_mm_element.classList.add("night");
        } else {
            hh_mm_element.classList.remove("day-selected");
            hh_mm_element.classList.add("day");
        }
        selectedHhMm15 = undefined;
    }
}

// Function to update the current_image element
async function updateCurrentImage(pictureData, hh_mm) {
    console.log(".updateCurrentImage('" + pictureData + "', '" + hh_mm + "')");
    const currentImage = pictureData.img;
    console.log("\t-> currentImage = " + currentImage);

    await unselectPictureSelector();

    // Change the src attribute of the main image
    document.getElementById("capture-img").src = "../captures/" + picturesProperties.sensor + "/" + picturesProperties.year + "/" + picturesProperties.month_day + "/" + currentImage;

    const parts = currentImage.split(/[_-]|Z/g); // Split by '_', '-', and 'Z'
    hour = parseInt(parts[4], 10);
    minute = parseInt(parts[5], 10);

    selectedHhMm15 = hhMm15SelectorFor(parts[4] + "h" + parts[5]);
    selectedPicture = pictureData;
    const hh_mm_element = document.getElementById(selectedHhMm15);
    if (pictureData.fSize < SIZE_LIMIT) {
        hh_mm_element.classList.remove("night");
        hh_mm_element.classList.add("night-selected");
    } else {
        hh_mm_element.classList.remove("day");
        hh_mm_element.classList.add("day-selected");
    }

    document.getElementById("current_hh_mm").textContent = hour + ":" + minute.toString().padStart(2, '0');

    index = sortedPictures.indexOf(hh_mm);
    if (index > 0) {
        makeElementClickable(document.getElementById("previous_hh_mm"));
    } else {
        makeElementNotClickable(document.getElementById("previous_hh_mm"));
    }
    if (index < sortedPictures.length - 1) {
        makeElementClickable(document.getElementById("next_hh_mm"));
    } else {
        makeElementNotClickable(document.getElementById("next_hh_mm"));
    }

    // TODO Check consistency with picturesProperties
    document.getElementById("error_message").textContent = picturesProperties.error_message; // TODO Implement error message display
    if (picturesProperties.error_message !== "") {
        alert("Error:\n" + picturesProperties.error_message);
    }

    // await updateDateData(); // NOT TO DO WITHIN .updateCurrentImage()
}

function grayPictureSelectorWithoutEvent() {
    console.log(".grayPictureSelectorWithoutEvent()");
    for (let hour = 0; hour <= 23; hour++) {
        for (let minute = 0; minute < 60; minute += 15) {
            // Format the hour and minute as "HHhMM"
            const formattedHour = hour.toString().padStart(2, '0');
            const formattedMinute = minute.toString().padStart(2, '0');
            // Create the time string
            const hh_mm = `${formattedHour}h${formattedMinute}`;
            // Assuming hh_mm_element is your HTML element
            const hh_mm_element = document.getElementById(hh_mm);
            // Get the event listeners for the "click" event

            const text = hh_mm_element.textContent;
            // Check if there are click event listeners
            if (text === "—") {
                document.getElementById(hh_mm).classList.remove("day", "night");
                document.getElementById(hh_mm).classList.add("no-picture-cell");
            }
        }
    }
}

function hhMm15SelectorFor(hh_mm) {
    console.log(".hhMm15SelectorFor('" + hh_mm + "')");
    const mm = hh_mm.slice(-2);
    const mmAsInt = parseInt(mm);
    let hh_mm15;
    if (mmAsInt % 15 === 0) {
        // mmAsInt is a multiple of 15
        hh_mm15 = hh_mm;
    } else {
        // mmAsInt is not a multiple of 15
        hh_mm15 = hh_mm.substring(0, 3) + (mmAsInt - (mmAsInt % 15)).toString();
    }
    return hh_mm15;
}

async function fillPictureSelectorHhMm(hh_mm, pictureData) {
    console.log(".fillPictureSelectorHhMm('" + hh_mm + "', '" + pictureData + "')");
    const mm = hh_mm.slice(-2);
    const hh_mm15 = hhMm15SelectorFor(hh_mm);

    // Get the hh_mm_element by its ID
    const hh_mm_element = document.getElementById(hh_mm15);

    hh_mm_element.textContent = mm;

    // console.log("DOMContentLoaded - addEventListener: '" + hh_mm + "' -> '" + pictureData + "'")
    hh_mm_element.addEventListener("click", function () {
        updateCurrentImage(pictureData, hh_mm);
    });
    // Add an event listener to each table cell

    hh_mm_element.classList.remove("no-picture-cell");
    if (pictureData.fSize < SIZE_LIMIT) {
        hh_mm_element.classList.add("night");
        hh_mm_element.classList.remove("day");
    } else {
        hh_mm_element.classList.add("day");
        hh_mm_element.classList.remove("night");
    }

    makeElementClickable(hh_mm_element);
}

function makeElementClickable(element) {
    console.log(".makeElementClickable(-> element.id='" + element.id + "')");
    element.style.cursor = "pointer";

    // todo Replaceable with .buttonEnabled ?
    // Add a mouseover event listener
    element.addEventListener("mouseover", function () {
        element.classList.add("hovered-cell");
    });
    // Add a mouseout event listener
    element.addEventListener("mouseout", function () {
        element.classList.remove("hovered-cell");
    });

    element.classList.remove("buttonDisabled");
    element.classList.add("buttonEnabled");
}

function makeElementNotClickable(element) {
    console.log(".makeElementNotClickable(...)");
    element.style.cursor = "default";

    // Remove mouseover event listener
    element.removeEventListener("mouseover", function () {
    });
    // Add a mouseout event listener
    element.removeEventListener("mouseout", function () {
    });

    element.classList.remove("buttonEnabled");
    element.classList.add("buttonDisabled");
}

function firstDaylightClickHandler() {
    console.log(".firstDaylightClickHandler()");
    updateCurrentImage(picturesData[firstDaylightHhMm], firstDaylightHhMm);
}

function lastDaylightClickHandler() {
    console.log(".lastDaylightClickHandler()");
    updateCurrentImage(picturesData[lastDaylightHhMm], lastDaylightHhMm);
}

async function fillPicturesSelector() {
    console.log(".fillPicturesSelector()");
    // Iterate through each element inside "pictures"
    for (const element_hh_mm in picturesData) { // rely on
        //if (picturesData.hasOwnProperty(element_hh_mm)) {
        let pictureData = {};
        pictureData.img = undefined;
        pictureData.fSize = undefined;
        pictureData = picturesData[element_hh_mm];
        console.log(`Element ${element_hh_mm}:`, pictureData);
        await fillPictureSelectorHhMm(element_hh_mm, pictureData);
        if ((firstDaylightHhMm === undefined) && pictureData.fSize > SIZE_LIMIT) {
            firstDaylightHhMm = element_hh_mm;
            const firstDaylightElement = document.getElementById("firstDaylight");
            firstDaylightElement.addEventListener("click", firstDaylightClickHandler);
            makeElementClickable(firstDaylightElement);
        }
        if (pictureData.fSize > SIZE_LIMIT) {
            lastDaylightHhMm = element_hh_mm;
            const LastDaylightElement = document.getElementById("lastDaylight");
            LastDaylightElement.addEventListener("click", lastDaylightClickHandler);
            makeElementClickable(LastDaylightElement);
        }
        //}
        lastHhMm = element_hh_mm;
    }
    grayPictureSelectorWithoutEvent()
}

async function previousHhMm() {
    console.log(".previousHhMm()");
    const previousKey = index > 0 ?
        sortedPictures[index - 1] : sortedPictures[0];
    await updateCurrentImage(picturesData[previousKey], previousKey);
}

async function nextHhMm() {
    console.log(".nextHhMm()");
    const nextKey = index < sortedPictures.length - 1 ?
        sortedPictures[index + 1] : sortedPictures[sortedPictures.length - 1];
    await updateCurrentImage(picturesData[nextKey], nextKey);
}

async function clearData() {
    console.log(".clearData()");
    hour = undefined; // :int
    minute = undefined; // :int
    firstDaylightHhMm = undefined;
    lastDaylightHhMm = undefined;
    lastHhMm = undefined;

    picturesData = {};
    picturesProperties = {};
    sortedPictures = undefined;
    index = undefined;
    await unselectPictureSelector();
    selectedPicture = undefined;

    // Reset content of Top Picture Selector
    for (let hour = 0; hour <= 23; hour++) {
        for (let minute = 0; minute < 60; minute += 15) {
            // Format the hour and minute as "HHhMM"
            const formattedHour = hour.toString().padStart(2, '0');
            const formattedMinute = minute.toString().padStart(2, '0');
            // Create the time string
            const hh_mm = `${formattedHour}h${formattedMinute}`;
            document.getElementById(hh_mm).textContent = "—";
        }
    }

    // Reset first/last day-light selection button:
    const firstDaylightElement = document.getElementById("firstDaylight");
    firstDaylightElement.removeEventListener("click", firstDaylightClickHandler);
    makeElementNotClickable(firstDaylightElement);
    const lastDaylightElement = document.getElementById("lastDaylight");
    lastDaylightElement.removeEventListener("click", lastDaylightClickHandler);
    makeElementNotClickable(lastDaylightElement);

    // Return a resolved promise to ensure the asynchronous completion
    return Promise.resolve();
}

async function refresh() {
    console.log(".refresh()");
    // Add safety check before splitting
    if (!picturesProperties.month_day) {
        console.error("picturesProperties.month_day is null or undefined in refresh()");
        return;
    }
    const sensor = picturesProperties.sensor;
    const year = picturesProperties.year;
    const [month, day] = picturesProperties.month_day.split("-");

    await refreshDate(sensor, year, month, day);
}

async function refreshDate(sensor, year, month, day) {
    console.log(".refreshDate('" + sensor + "', '" + year + "', '" + month + "', '" + day + "')");
    // Wait for clearData to complete before proceeding
    await clearData();
    // Call fetchData function to get data after page loaded:
    await fetchData(sensor, year, month, day); // Wait for fetchData to complete
    console.log("\tafter fetchData call:", picturesData, picturesProperties);
    const picturesFolder = "captures/" + picturesProperties.sensor + "/";
    console.log("\tpicturesFolder =", picturesFolder);

    await fillPicturesSelector();
    console.log("picturesData = " + picturesData);
    if (lastDaylightHhMm !== undefined) {
        console.log("lastDaylightHhMm = " + lastDaylightHhMm);
        const pictureData = picturesData[lastDaylightHhMm];
        console.log("pictureData = ", pictureData)
        await updateCurrentImage(pictureData, lastDaylightHhMm);
    } else if (lastHhMm !== undefined) {
        const pictureData = picturesData[lastHhMm];
        await updateCurrentImage(pictureData, lastHhMm);
    } else {
        // Change the src attribute of the main image
        document.getElementById("capture-img").src = "../html/undefined_4x3.png";
        document.getElementById("error_message").textContent = "No pictures for this date!";
    }

    await updateDateData();
}

document.addEventListener("DOMContentLoaded", async function () {
    console.log("DOMContentLoaded - ---DOMContentLoaded-start---");
    // Get the current URL
    const currentUrl = new URL(window.location.href);
    // Extract parameters using URLSearchParams
    let paramSensor = currentUrl.searchParams.get("s");
    let paramYear = currentUrl.searchParams.get("y");
    let paramMonth = currentUrl.searchParams.get("m");
    let paramDay = currentUrl.searchParams.get("d");

    // Convert string 'null' to actual null
    if (paramSensor === 'null' || paramSensor === '') paramSensor = null;
    if (paramYear === 'null' || paramYear === '') paramYear = null;
    if (paramMonth === 'null' || paramMonth === '') paramMonth = null;
    if (paramDay === 'null' || paramDay === '') paramDay = null;

    // Use current date as fallback if no valid parameters
    if (!paramSensor || !paramYear || !paramMonth || !paramDay) {
        const now = new Date();
        paramSensor = paramSensor || 'tilleul';
        paramYear = paramYear || now.getFullYear();
        paramMonth = paramMonth || (now.getMonth() + 1);
        paramDay = paramDay || now.getDate();
        console.log("Using fallback date:", paramSensor, paramYear, paramMonth, paramDay);
    }

    await refreshDate(paramSensor, paramYear, paramMonth, paramDay);

    console.log("DOMContentLoaded - ---DOMContentLoaded-end---");
});

console.log("---End---");
