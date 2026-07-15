from flask import Flask, request, jsonify, render_template
from bs4 import BeautifulSoup
import requests
import traceback
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


def extract_text(soup, element_id):
    """Safely extract text from an HTML element."""
    element = soup.find(id=element_id)
    return element.get_text(strip=True) if element else ""


@app.route("/api/fetch-result", methods=["POST"])
def fetch_result():

    debug = []

    try:

        debug.append("API Started")

        data = request.get_json(force=True)

        if not data:
            return jsonify({
                "error": "No JSON body received",
                "debug": debug
            }), 400

        roll_no = str(data.get("rollNo", "")).strip()

        debug.append(f"Roll Number = {roll_no}")

        if not roll_no:
            return jsonify({
                "error": "Roll number is required",
                "debug": debug
            }), 400

        session = requests.Session()

        target_url = "https://oneview.aktu.ac.in/WebPages/AKTU/OneView.aspx"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,"
                      "application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

        debug.append("Opening AKTU OneView...")

        initial_response = session.get(
            target_url,
            headers=headers,
            verify=False,
            timeout=30
        )

        debug.append(f"GET Status = {initial_response.status_code}")
        debug.append(f"GET URL = {initial_response.url}")
        debug.append(f"GET Length = {len(initial_response.text)}")

        debug.append(initial_response.text[:400])

        initial_response.raise_for_status()

        soup = BeautifulSoup(initial_response.text, "html.parser")
        # --------------------------------------------------
        # Extract ALL hidden ASP.NET fields
        # --------------------------------------------------

        payload = {}

        hidden_inputs = soup.find_all("input", {"type": "hidden"})

        debug.append(f"Hidden fields found = {len(hidden_inputs)}")

        for hidden in hidden_inputs:
            name = hidden.get("name")
            value = hidden.get("value", "")

            if name:
                payload[name] = value

        debug.append(
            "Hidden field names: " +
            ", ".join(list(payload.keys())[:20])
        )

        # --------------------------------------------------
        # Add Roll Number
        # --------------------------------------------------

        payload["txtRollNo"] = roll_no

        # Different versions of OneView use different button names.
        # We will try the common one first.

        payload["btnSearch"] = "Search"

        post_headers = headers.copy()

        post_headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://oneview.aktu.ac.in",
            "Referer": target_url
        })

        debug.append("Submitting POST request...")

        result_response = session.post(
            target_url,
            data=payload,
            headers=post_headers,
            verify=False,
            timeout=40
        )

        debug.append(f"POST Status = {result_response.status_code}")
        debug.append(f"POST Length = {len(result_response.text)}")

        html = result_response.text

        debug.append(html[:600])

        result_response.raise_for_status()

        # --------------------------------------------------
        # Detect Cloudflare / blocked pages
        # --------------------------------------------------

        lower = html.lower()

        if "cloudflare" in lower:
            return jsonify({
                "error": "Cloudflare protection detected.",
                "debug": debug
            }), 500

        if "access denied" in lower:
            return jsonify({
                "error": "Access Denied by AKTU server.",
                "debug": debug
            }), 500

        if "captcha" in lower:
            return jsonify({
                "error": "Captcha detected.",
                "debug": debug
            }), 500

        if "temporarily unavailable" in lower:
            return jsonify({
                "error": "AKTU portal temporarily unavailable.",
                "debug": debug
            }), 500

        debug.append("POST request successful.")

        result_soup = BeautifulSoup(html, "html.parser")
        # ----------------------------------------------------
        # Check for server-side error
        # ----------------------------------------------------

        error = result_soup.find(id="lblError")

        if error and error.get_text(strip=True):
            return jsonify({
                "error": error.get_text(strip=True),
                "debug": debug
            }), 400

        debug.append("No lblError found.")

        # ----------------------------------------------------
        # Student Details
        # ----------------------------------------------------

        student_info = {
            "name": extract_text(result_soup, "lblName"),
            "rollNo": roll_no,
            "enrollmentNo": extract_text(result_soup, "lblEnrollmentNo"),
            "fatherName": extract_text(result_soup, "lblFatherName"),
            "course": extract_text(result_soup, "lblCourse"),
            "branch": extract_text(result_soup, "lblBranch"),
            "institute": extract_text(result_soup, "lblInstitute")
        }

        debug.append("Student Details Extracted")

        for k, v in student_info.items():
            debug.append(f"{k} = {v}")

        # ----------------------------------------------------
        # Find every table
        # ----------------------------------------------------

        tables = result_soup.find_all("table")

        debug.append(f"Tables Found = {len(tables)}")

        semesters = []
        # ----------------------------------------------------
        # Parse all tables (Debug Parser)
        # ----------------------------------------------------

        for table_index, table in enumerate(tables):

            rows = table.find_all("tr")

            if len(rows) < 2:
                continue

            debug.append(f"Checking Table {table_index} ({len(rows)} rows)")

            subjects = []

            for row in rows:

                cols = [
                    td.get_text(" ", strip=True)
                    for td in row.find_all(["td", "th"])
                ]

                if len(cols) < 5:
                    continue

                # Skip header row
                if "subject" in cols[1].lower():
                    continue

                subjects.append({
                    "code": cols[0],
                    "name": cols[1],
                    "internal": cols[2] if len(cols) > 2 else "--",
                    "external": cols[3] if len(cols) > 3 else "--",
                    "grade": cols[4] if len(cols) > 4 else "--",
                    "backPaper": "--"
                })

            if len(subjects) == 0:
                continue

            debug.append(
                f"Table {table_index} contains {len(subjects)} subjects."
            )

            semesters.append({

                "semester": str(len(semesters) + 1),

                "session": "",

                "evenOdd": "",

                "sgpa": "",

                "resultStatus": "",

                "totalMarksObt": "",

                "declarationDate": "",

                "subjects": subjects

            })

        debug.append(f"Semesters Parsed = {len(semesters)}")
        return jsonify({

            "studentInfo": student_info,

            "semesters": semesters,

            "dobRequired": False,

            "debug": debug

        }), 200
    except requests.exceptions.RequestException as e:

        return jsonify({

            "error": str(e),

            "traceback": traceback.format_exc(),

            "debug": debug

        }), 502


    except Exception as e:

        return jsonify({

            "error": str(e),

            "traceback": traceback.format_exc(),

            "debug": debug

        }), 500
@app.route("/test")
def test():
    import requests

    try:
        r = requests.get("https://oneview.aktu.ac.in", timeout=10)
        return str(r.status_code)
    except Exception as e:
        return str(e)
if __name__ == "__main__":
    app.run(debug=True, port=5000)
