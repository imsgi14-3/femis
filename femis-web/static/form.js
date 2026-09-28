/* FEMIS Web — Cascading dropdowns, conditional fields, AJAX save, dirty tracking */

document.addEventListener("DOMContentLoaded", function () {

    // === Helpers ===
    var isDirty = false;
    var studentId = document.getElementById("student_id");
    var currentTab = 0;
    var tabIds = ["tab-1", "tab-2", "tab-3", "tab-4", "tab-5", "tab-6", "tab-7"];
    var tabPills = document.querySelectorAll(".nav-pills .nav-link");

    // === Auto-format CNIC: XXXXX-XXXXXXX-X ===
    function formatCNIC(input) {
        var val = input.value.replace(/[^0-9]/g, "");
        var formatted = "";
        if (val.length > 0) formatted += val.substring(0, 5);
        if (val.length > 5) formatted += "-" + val.substring(5, 12);
        if (val.length > 12) formatted += "-" + val.substring(12, 13);
        input.value = formatted;
    }

    // === Auto-format Mobile: 0XXX-XXXXXXX ===
    function formatMobile(input) {
        var val = input.value.replace(/[^0-9]/g, "");
        var formatted = "";
        if (val.length > 0) formatted += val.substring(0, 4);
        if (val.length > 4) formatted += "-" + val.substring(4, 11);
        input.value = formatted;
    }

    // Attach CNIC formatting
    document.querySelectorAll('input[name="b_form"], input[name="father_cnic"], input[name="mother_cnic"], input[name="guardian_cnic"]').forEach(function (el) {
        el.addEventListener("input", function () { formatCNIC(this); });
    });

    // Attach Mobile formatting
    document.querySelectorAll('input[name="contact_number"], input[name="father_contact"], input[name="mother_contact"], input[name="guardian_contact"], input[name="emergency_contact"]').forEach(function (el) {
        el.addEventListener("input", function () { formatMobile(this); });
    });

    function selectToggle(selectName, containerId, showValues) {
        var sel = document.querySelector('select[name="' + selectName + '"]');
        var container = document.getElementById(containerId);
        if (!sel || !container) return;
        function toggle() {
            var val = sel.value;
            container.style.display = showValues.indexOf(val) >= 0 ? "block" : "none";
        }
        sel.addEventListener("change", toggle);
        toggle();
    }

    function radioToggle(name, containerId, showValues) {
        var radios = document.querySelectorAll('input[name="' + name + '"]');
        var container = document.getElementById(containerId);
        if (!radios.length || !container) return;
        function toggle() {
            var selected = document.querySelector('input[name="' + name + '"]:checked');
            var val = selected ? selected.value : "";
            container.style.display = showValues.indexOf(val) >= 0 ? "block" : "none";
        }
        radios.forEach(function (r) { r.addEventListener("change", toggle); });
        toggle();
    }

    function checkboxToggle(checkboxId, containerId, showWhenUnchecked) {
        var cb = document.getElementById(checkboxId);
        var container = document.getElementById(containerId);
        if (!cb || !container) return;
        function toggle() {
            container.style.display = (cb.checked === showWhenUnchecked) ? "none" : "block";
        }
        cb.addEventListener("change", toggle);
        toggle();
    }

    // === Cascading: Select Province → District ===
    function setupSelectCascading(selectName, districtId) {
        var sel = document.querySelector('select[name="' + selectName + '"]');
        var districtEl = document.getElementById(districtId);
        if (!sel || !districtEl) return;

        function loadDistricts(provinceText) {
            districtEl.innerHTML = '<option value="">Loading...</option>';
            districtEl.disabled = true;
            if (!provinceText) {
                districtEl.innerHTML = '<option value="">Select Province first</option>';
                districtEl.disabled = false;
                return;
            }
            fetch("/api/districts/" + encodeURIComponent(provinceText))
                .then(function (r) { return r.json(); })
                .then(function (districts) {
                    var pending = districtEl.getAttribute("data-pending-value");
                    districtEl.innerHTML = '<option value="">Select District</option>';
                    districts.forEach(function (d) {
                        var opt = document.createElement("option");
                        opt.value = d; opt.textContent = d;
                        districtEl.appendChild(opt);
                    });
                    districtEl.disabled = false;
                    if (pending) {
                        districtEl.value = pending;
                        districtEl.removeAttribute("data-pending-value");
                    }
                })
                .catch(function () {
                    districtEl.innerHTML = '<option value="">Error loading districts</option>';
                });
        }

        sel.addEventListener("change", function () {
            var selectedText = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : "";
            loadDistricts(selectedText);
        });
    }

    setupSelectCascading("birth_province_id", "birth_district_id");
    setupSelectCascading("domicile_province_id", "domicile_district_id");
    setupSelectCascading("father_domicile_province_id", "father_domicile_district_id");

    // === Cascading: Sector → Sub-sector (for temp address) ===
    function setupSectorCascade(prefix) {
        var sectorSelect = document.getElementById(prefix + "sector_select");
        var subSectorSelect = document.getElementById(prefix + "sub_sector_select");
        var subSectorDiv = document.getElementById(prefix + "sub_sector_group");
        if (!sectorSelect || !subSectorSelect) return;

        sectorSelect.addEventListener("change", function () {
            var sectorText = this.options[this.selectedIndex] ? this.options[this.selectedIndex].text : "";
            if (!sectorText || this.value === "") {
                subSectorSelect.innerHTML = '<option value="">- Select Sector first -</option>';
                if (subSectorDiv) subSectorDiv.style.display = "none";
                return;
            }
            fetch("/api/sub-sectors/" + encodeURIComponent(sectorText))
                .then(function (r) { return r.json(); })
                .then(function (subSectors) {
                    var pending = subSectorSelect.getAttribute("data-pending-value");
                    subSectorSelect.innerHTML = '<option value="">- Select -</option>';
                    if (subSectors.length === 0) {
                        if (subSectorDiv) subSectorDiv.style.display = "none";
                        return;
                    }
                    subSectors.forEach(function (ss) {
                        var opt = document.createElement("option");
                        opt.value = ss; opt.textContent = ss;
                        subSectorSelect.appendChild(opt);
                    });
                    if (pending) {
                        subSectorSelect.value = pending;
                        subSectorSelect.removeAttribute("data-pending-value");
                    }
                    if (subSectorDiv) subSectorDiv.style.display = "block";
                })
                .catch(function () {
                    subSectorSelect.innerHTML = '<option value="">Error loading</option>';
                });
        });
    }

    setupSectorCascade("");
    setupSectorCascade("present_");

    // === Conditional: CNIC Available → show/hide CNIC field ===
    (function () {
        var radios = document.querySelectorAll('input[name="is_bform_available"]');
        var cnicGroup = document.getElementById("cnic_number_group");
        var cnicInput = document.getElementById("cnic_number_input");
        function toggle() {
            var selected = document.querySelector('input[name="is_bform_available"]:checked');
            var val = selected ? selected.value : "";
            if (val === "1") {
                if (cnicGroup) cnicGroup.style.display = "block";
                if (cnicInput) cnicInput.required = true;
            } else {
                if (cnicGroup) cnicGroup.style.display = "none";
                if (cnicInput) cnicInput.required = false;
                if (cnicInput) cnicInput.value = "";
            }
        }
        radios.forEach(function (r) { r.addEventListener("change", toggle); });
        toggle();
    })();

    // === Conditional: Address Type (select) → Show/Hide fields (temp) ===
    (function () {
        var sel = document.getElementById("address_type");
        var sectorDiv = document.getElementById("sector_group");
        var subSectorDiv = document.getElementById("sub_sector_group");
        var villageDiv = document.getElementById("village_group");
        var hsDiv = document.getElementById("housing_society_group");
        var otherDiv = document.getElementById("other_address_group");
        var houseStreet = document.getElementById("house_street_group");
        var houseInput = document.querySelector('input[name="house"]');
        var streetInput = document.querySelector('input[name="street"]');

        if (!sel) return;
        function toggle() {
            var val = sel.value;
            var isOther = val === "Other";
            if (sectorDiv) sectorDiv.style.display = val === "Sector" ? "block" : "none";
            if (subSectorDiv) subSectorDiv.style.display = val === "Sector" ? "block" : "none";
            if (villageDiv) villageDiv.style.display = val === "Village" ? "block" : "none";
            if (hsDiv) hsDiv.style.display = val === "Housing Society" ? "block" : "none";
            if (otherDiv) otherDiv.style.display = isOther ? "block" : "none";
            if (houseStreet) houseStreet.style.display = isOther ? "none" : "block";
            if (houseInput) houseInput.required = !isOther;
            if (streetInput) streetInput.required = !isOther;
        }
        sel.addEventListener("change", toggle);
        toggle();
    })();

    // === Conditional: Present Address Type (select) → Show/Hide fields (permanent) ===
    (function () {
        var sel = document.getElementById("present_address_type");
        var sectorDiv = document.getElementById("present_sector_group");
        var subSectorDiv = document.getElementById("present_sub_sector_group");
        var villageDiv = document.getElementById("present_village_group");
        var hsDiv = document.getElementById("present_housing_society_group");
        var otherDiv = document.getElementById("present_other_address_group");
        var houseStreet = document.getElementById("present_house_street_group");

        if (!sel) return;
        function toggle() {
            var val = sel.value;
            var isOther = val === "Other";
            if (sectorDiv) sectorDiv.style.display = val === "Sector" ? "block" : "none";
            if (subSectorDiv) subSectorDiv.style.display = val === "Sector" ? "block" : "none";
            if (villageDiv) villageDiv.style.display = val === "Village" ? "block" : "none";
            if (hsDiv) hsDiv.style.display = val === "Housing Society" ? "block" : "none";
            if (otherDiv) otherDiv.style.display = isOther ? "block" : "none";
            if (houseStreet) houseStreet.style.display = isOther ? "none" : "block";
        }
        sel.addEventListener("change", toggle);
        toggle();
    })();

    // === Conditional: Nationality (select) → show Other Nationality ===
    selectToggle("nationality", "nationality_other_group", ["Other"]);

    // === Conditional: Religion (select) → show Other Religion ===
    selectToggle("religion", "other_religion_group", ["Non-Muslim"]);

    // === Visibility parity with FEMIS portal (misalignment report §6-P3) ===
    selectToggle("gender", "girls_stipend_group", ["Female"]);
    selectToggle("nationality", "domicile_fields", ["Pakistani"]);
    selectToggle("religion", "hafiz_group", ["Muslim"]);
    selectToggle("guardian_profession", "guardian_bps_group", ["Govt Employee"]);

    // === Mother's Income asterisk: show only when enforced (rule §8-8.1) ===
    (function () {
        var prof = document.getElementById("mother_profession");
        var star = document.getElementById("mother_income_required");
        if (!prof || !star) return;
        function toggleStar() {
            var v = (prof.value || "").trim().toLowerCase();
            star.style.display = (v && v !== "housewife") ? "inline" : "none";
        }
        prof.addEventListener("change", toggleStar);
        toggleStar();
    })();

    // === Conditional: Same as Temp → show/hide permanent address fields ===
    checkboxToggle("same_as_temporary", "permanent_address_fields", true);

    // === Same as Temporary Address → auto-fill permanent fields ===
    (function () {
        var cb = document.getElementById("same_as_temporary");
        if (!cb) return;
        var pairs = [
            ["address_type", "present_address_type"],
            ["sector_id", "present_sector_id"],
            ["sub_sector_id", "present_sub_sector_id"],
            ["village_id", "present_village_id"],
            ["housing_society_id", "present_housing_society_id"],
            ["house", "present_house"],
            ["street", "present_street"],
        ];
        function copyVal(src, dst) {
            if (!src || !dst) return;
            if (dst.tagName === "SELECT") {
                if (src.value && Array.from(dst.options).every(function (o) { return o.value !== src.value; })) {
                    dst.setAttribute("data-pending-value", src.value);
                } else {
                    dst.removeAttribute("data-pending-value");
                }
                dst.value = src.value;
                dst.dispatchEvent(new Event("change", { bubbles: true }));
            } else {
                dst.value = src.value;
                dst.dispatchEvent(new Event("input", { bubbles: true }));
                dst.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }
        function copyAddresses() {
            if (!cb.checked) return;
            pairs.forEach(function (p) {
                copyVal(
                    document.querySelector('[name="' + p[0] + '"]'),
                    document.querySelector('[name="' + p[1] + '"]')
                );
            });
        }
        cb.addEventListener("change", copyAddresses);
        pairs.forEach(function (p) {
            var src = document.querySelector('[name="' + p[0] + '"]');
            if (src) {
                src.addEventListener("change", function () { if (cb.checked) copyAddresses(); });
                src.addEventListener("input", function () { if (cb.checked) copyAddresses(); });
            }
        });
    })();

    // === Total Siblings: digits only, no leading zeros (1/2/3 — not 01/02) ===
    (function () {
        var el = document.querySelector('input[name="total_siblings"]');
        if (!el) return;
        el.addEventListener("input", function () {
            var v = el.value.replace(/[^0-9]/g, "").replace(/^0+(?=[0-9])/, "");
            if (v !== el.value) el.value = v;
        });
    })();

    // === Father Alive → show details only ===
    radioToggle("is_father_alive", "father_details_group", ["1"]);

    // === Mother Alive → show details only ===
    radioToggle("is_mother_alive", "mother_details_group", ["1"]);

    // === Orphan → guardian always visible; orphan_type required only if Yes ===
    // (orphan_fields stays visible for always-required guardian fields)

    // === Auto-set is_orphan=yes + orphan_type when parent(s) dead ===
    (function () {
        var fatherRadios = document.querySelectorAll('input[name="is_father_alive"]');
        var motherRadios = document.querySelectorAll('input[name="is_mother_alive"]');
        var orphanYes = document.getElementById("is_orphan_yes");
        var orphanNo = document.getElementById("is_orphan_no");
        var orphanTypeSelect = document.getElementById("orphan_type");
        if (!orphanYes) return;
        function checkParentStatus() {
            var fatherSel = document.querySelector('input[name="is_father_alive"]:checked');
            var motherSel = document.querySelector('input[name="is_mother_alive"]:checked');
            var fatherDead = fatherSel && fatherSel.value === "0";
            var motherDead = motherSel && motherSel.value === "0";
            if (fatherDead || motherDead) {
                orphanYes.checked = true;
                orphanYes.dispatchEvent(new Event("change"));
                if (orphanTypeSelect) {
                    if (fatherDead && motherDead) {
                        orphanTypeSelect.value = "Double Orphan";
                    } else {
                        orphanTypeSelect.value = "Single Orphan";
                    }
                    orphanTypeSelect.dispatchEvent(new Event("change"));
                }
            } else if (fatherSel && fatherSel.value === "1" && motherSel && motherSel.value === "1") {
                orphanNo.checked = true;
                orphanNo.dispatchEvent(new Event("change"));
                if (orphanTypeSelect) orphanTypeSelect.value = "";
            }
        }
        fatherRadios.forEach(function (r) { r.addEventListener("change", checkParentStatus); });
        motherRadios.forEach(function (r) { r.addEventListener("change", checkParentStatus); });

        // Selecting Orphan = Yes while BOTH parents are alive is invalid —
        // flip it back to No immediately (validateTab's orphan guard remains
        // the save-time backstop for records loaded from elsewhere).
        document.querySelectorAll('input[name="is_orphan"]').forEach(function (r) {
            r.addEventListener("change", function () {
                if (!this.checked || this.value !== "1" || !orphanNo) return;
                var fa = document.querySelector('input[name="is_father_alive"]:checked');
                var ma = document.querySelector('input[name="is_mother_alive"]:checked');
                if (fa && fa.value === "1" && ma && ma.value === "1") {
                    orphanNo.checked = true;
                    orphanNo.dispatchEvent(new Event("change"));
                    if (orphanTypeSelect) orphanTypeSelect.value = "";
                    alert("Is Orphan cannot be Yes when both parents are alive.");
                }
            });
        });
    })();

    // === Father Profession (select) → show Other + show BPS only for Govt Employee ===
    selectToggle("father_profession", "father_profession_other_group", ["Other"]);
    (function () {
        var profSel = document.getElementById("father_profession");
        var bpsDiv = document.getElementById("father_bps_group");
        if (!profSel) return;
        function toggleBps() {
            if (bpsDiv) bpsDiv.style.display = profSel.value === "Govt Employee" ? "block" : "none";
        }
        profSel.addEventListener("change", toggleBps);
        toggleBps();
    })();

    // === Mother Profession (select) → show Other + show BPS only for Govt Employee ===
    selectToggle("mother_profession", "mother_profession_other_group", ["Other"]);
    selectToggle("mother_profession", "mother_bps_group", ["Govt Employee"]);

    // === Guardian Relation (select) → show Other ===
    selectToggle("guardian_relation", "guardian_relation_other_group", ["Other"]);

    // === Guardian Profession (select) → show Other ===
    selectToggle("guardian_profession", "guardian_profession_other_group", ["Other"]);

    // === Mother Language (select) → show Other ===
    selectToggle("language_id", "mother_language_other_group", ["Other"]);

    // === Emergency Relation (select) → show Specify Relation for Others ===
    selectToggle("emergency_relation", "emergency_relation_other_group", ["Other", "Others"]);

    // === Mental Disability Type (select) → show Other ===
    selectToggle("mental_disability_type", "mental_disability_other_group", ["Other"]);

    // === Wears Glasses → show prescription ===
    // FEMIS: Glasses Prescription required when Visually FIT = No
    radioToggle("visually_fit", "glass_prescription_group", ["0"]);

    // === Hearing Aid details ← Has Hearing Difficulty = Yes (portal click-map) ===
    radioToggle("has_hearing_difficulties", "hearing_aid_details_group", ["1"]);

    // === Class → Section dynamic: 1-8 → A,B; 9-10 → A,B,C ===
    (function () {
        var sectionGroup = document.getElementById("section_group");
        if (!sectionGroup) return;
        var classRadios = document.querySelectorAll('input[name="class_id"]');
        function updateSections() {
            var checked = document.querySelector('input[name="class_id"]:checked');
            if (!checked) return;
            var classText = checked.value;
            var classNum = parseInt(classText.replace("Class ", ""), 10);
            var sections = classNum >= 9 ? ["A", "B", "C"] : ["A", "B"];
            var currentSection = document.querySelector('input[name="section_id"]:checked');
            var currentVal = currentSection ? currentSection.value : "";
            sectionGroup.innerHTML = "";
            sections.forEach(function (s) {
                var div = document.createElement("div");
                div.className = "form-check form-check-inline";
                var input = document.createElement("input");
                input.className = "form-check-input";
                input.type = "radio";
                input.name = "section_id";
                input.id = "section_" + s;
                input.value = s;
                if (s === currentVal) input.checked = true;
                var label = document.createElement("label");
                label.className = "form-check-label";
                label.htmlFor = "section_" + s;
                label.textContent = s;
                div.appendChild(input);
                div.appendChild(label);
                sectionGroup.appendChild(div);
            });
        }
        classRadios.forEach(function (r) { r.addEventListener("change", updateSections); });
    })();
    radioToggle("has_major_disability", "disability_fields", ["1"]);
    radioToggle("has_mental_disability", "mental_disability_type_group", ["1"]);
    radioToggle("is_refugee", "idp_fields", ["1"]);
    radioToggle("is_registered_refugee", "refugee_card_group", ["1"]);
    radioToggle("digital_device_at_home", "device_type_group", ["1"]);
    radioToggle("transport_facility", "bus_route_group", ["Institution Bus"]);
    radioToggle("scholarship", "scholarship_details_group", ["1"]);
    radioToggle("cocurricular_activities", "co_curricular_details_group", ["1"]);

    // === Orphan Type ← is_orphan=Yes; Guardian block ← father not alive (FEMIS) ===
    radioToggle("is_orphan", "orphan_type_group", ["1"]);
    radioToggle("is_father_alive", "guardian_group", ["0"]);

    // === Class Admitted In options follow selected Class ===
    // Class 1-5 → admitted 1..5; Class 6-10 → admitted 6..10
    (function () {
        var caiGroup = document.getElementById("class_admitted_group");
        if (!caiGroup) return;
        var classRadios = document.querySelectorAll('input[name="class_id"]');
        function updateClassAdmitted() {
            var checked = document.querySelector('input[name="class_id"]:checked');
            if (!checked) return;
            var classNum = parseInt(checked.value, 10);
            if (isNaN(classNum)) return;
            var lo = classNum <= 5 ? 1 : 6;
            var hi = classNum <= 5 ? 5 : 10;
            var current = document.querySelector('input[name="class_admitted_id"]:checked');
            var currentVal = current ? current.value : "";
            caiGroup.innerHTML = "";
            for (var n = lo; n <= hi; n++) {
                var div = document.createElement("div");
                div.className = "form-check form-check-inline";
                var input = document.createElement("input");
                input.className = "form-check-input";
                input.type = "radio";
                input.name = "class_admitted_id";
                input.id = "cai_" + n;
                input.value = String(n);
                input.required = true;
                if (currentVal === String(n)) input.checked = true;
                var label = document.createElement("label");
                label.className = "form-check-label";
                label.htmlFor = "cai_" + n;
                label.textContent = "Class " + n;
                div.appendChild(input);
                div.appendChild(label);
                caiGroup.appendChild(div);
            }
        }
        classRadios.forEach(function (r) { r.addEventListener("change", updateClassAdmitted); });
        updateClassAdmitted();
    })();

    // === FDE Institution → Other text ===
    var fdeSelect = document.getElementById("last_institution_fde");
    var fdeOtherGroup = document.getElementById("last_institution_other_group");
    if (fdeSelect && fdeOtherGroup) {
        fdeSelect.addEventListener("change", function () {
            fdeOtherGroup.style.display = this.value === "Other" ? "block" : "none";
        });
    }

    // ==================================================================
    // DIRTY TRACKING + PREVENT LEGACY FORM POST
    // ==================================================================
    var form = document.getElementById("admissionForm");
    if (form) {
        form.addEventListener("input", function () { isDirty = true; });
        form.addEventListener("change", function () { isDirty = true; });
        form.addEventListener("submit", function (e) { e.preventDefault(); });
    }

    // ==================================================================
    // LOCKED STATE — disable all inputs if record is locked
    // ==================================================================
    var lockedField = document.getElementById("is_locked");
    var isLocked = lockedField && lockedField.value === "true";
    if (isLocked) {
        form.querySelectorAll("input, select, textarea, button").forEach(function (el) {
            if (el.id !== "student_id" && el.id !== "is_locked") {
                el.disabled = true;
            }
        });
        var btn = document.getElementById("save-next-btn");
        if (btn) btn.style.display = "none";
    }

    function markClean() { isDirty = false; }

    // ==================================================================
    // TAB SWITCHING with unsaved warning
    // Bootstrap fires show.bs.tab after click — cancel must block HERE,
    // otherwise preventDefault on click does not stop the tab switch.
    // ==================================================================
    tabPills.forEach(function (pill, idx) {
        pill.addEventListener("show.bs.tab", function (e) {
            if (!isDirty) return;
            if (!confirm("You have unsaved changes. Switching tabs will lose unsaved data.\n\nContinue?")) {
                e.preventDefault();
                e.stopPropagation();
                return false;
            }
            markClean();
        });
    });

    // ==================================================================
    // UPDATE BUTTON based on active tab
    // ==================================================================
    var saveNextBtn = document.getElementById("save-next-btn");
    var btnLabel = document.getElementById("btn-label");
    var btnArrow = document.getElementById("btn-arrow");

    function updateButton(tabIndex) {
        currentTab = tabIndex;
        if (tabIndex >= 6) {
            btnLabel.textContent = "Submit";
            btnArrow.className = "bi bi-check-circle ms-1";
            saveNextBtn.className = "btn btn-success btn-lg";
        } else {
            btnLabel.textContent = "Save & Next";
            btnArrow.className = "bi bi-arrow-right ms-1";
            saveNextBtn.className = "btn btn-primary btn-lg";
        }
    }

    tabPills.forEach(function (pill, idx) {
        pill.addEventListener("shown.bs.tab", function () { updateButton(idx); });
    });
    updateButton(0);

    // ==================================================================
    // MANDATORY FIELD VALIDATION per tab
    // Visibility-gated: fields inside a hidden group are NOT enforced —
    // mirrors FEMIS, which only requires what it currently shows
    // (misalignment report §6-P1.1/P1.2/P1.3).
    // ==================================================================
    var mandatoryByTab = {
        0: ["name", "is_bform_available", "b_form", "gender", "date_of_birth", "birth_province_id", "birth_district_id", "nationality", "address_type", "sector_id", "sub_sector_id", "contact_number", "city_id", "present_address_type", "present_sector_id", "present_sub_sector_id", "religion", "language_id", "email"],
        1: [
            "father_name", "father_cnic", "is_father_alive", "father_profession",
            "father_qualification", "father_monthly_income",
            "mother_name", "is_mother_alive", "mother_profession", "mother_qualification",
            "is_orphan",
        ],
        2: [
            "class_id", "section_id", "date_of_admission", "class_admitted_id",
            "medium_of_instruction", "mode_of_study", "admission_number", "shift",
            "total_siblings", "school_meal_program_availing",
            "transport_facility", "scholarship", "cocurricular_activities",
        ],
        3: ["emergency_name", "emergency_contact", "emergency_relation"],
        4: ["is_refugee"],
        5: [
            "has_major_disability", "has_mental_disability", "visually_fit",
            "uses_glasses", "has_hearing_difficulties", "difficulty_listening",
            "difficulty_walking", "uses_crutches_walker", "uses_hearing_aid",
            "difficulty_seeing_board", "difficulty_reading_writing",
            "difficulty_remembering", "difficulty_concentrating",
        ],
        6: ["digital_device_at_home", "internet_at_home"],
    };

    // Hidden-field detection: an element is hidden when any ancestor INSIDE
    // its tab pane has computed display:none. The pane itself is ignored so a
    // non-active pane can still be validated (final submit checks every tab).
    function isHiddenWithin(pane, el) {
        if (!el || !pane) return false;
        var node = el;
        while (node && node !== pane) {
            if (window.getComputedStyle(node).display === "none") return true;
            node = node.parentElement;
        }
        return false;
    }

    function fieldControl(pane, fname) {
        var radios = pane.querySelectorAll('input[type="radio"][name="' + fname + '"]');
        if (radios.length) return { kind: "radio", els: radios };
        var sel = pane.querySelector('select[name="' + fname + '"]');
        if (sel) return { kind: "select", els: [sel] };
        var checks = pane.querySelectorAll('input[type="checkbox"][name="' + fname + '"]');
        if (checks.length) return { kind: "checkbox", els: checks };
        var input = pane.querySelector('input:not([type="radio"]):not([type="checkbox"])[name="' + fname + '"], textarea[name="' + fname + '"]');
        if (input) return { kind: "text", els: [input] };
        return null;
    }

    function controlValue(ctl) {
        if (ctl.kind === "radio") {
            for (var i = 0; i < ctl.els.length; i++) {
                if (ctl.els[i].checked) return ctl.els[i].value;
            }
            return "";
        }
        if (ctl.kind === "checkbox") {
            // For [] groups the requirement is the control being rendered
            // (value semantics unchanged from rev.1).
            return ctl.els[0].value;
        }
        return ctl.els[0].value.trim();
    }

    function fieldLabel(pane, fname) {
        var label = pane.querySelector('label[for="' + fname + '"]');
        if (!label) {
            label = pane.querySelector('label:has(+ [name="' + fname + '"]), label:has(+ div [name="' + fname + '"])');
        }
        return label ? label.textContent.replace("*", "").trim() : fname;
    }

    function validateTab(tabIndex, pane) {
        var fields = mandatoryByTab[tabIndex];
        if (!fields) return true;
        if (!pane) pane = document.querySelector(".tab-pane.active");
        if (!pane) return true;
        var missing = [];
        fields.forEach(function (fname) {
            var ctl = fieldControl(pane, fname);
            if (!ctl) return;                            // control not rendered — nothing to fill
            if (isHiddenWithin(pane, ctl.els[0])) return; // hidden group → not enforced (§6-P1.3)
            if (!controlValue(ctl)) {
                missing.push(fieldLabel(pane, fname));
            }
        });

        // Conditional required fields — trigger on AND field group visible
        var conditionalRequired = [
            {fields: ["orphan_type"], trigger: "is_orphan", values: ["1"]},
            {fields: ["scholarship_details"], trigger: "scholarship", values: ["1"]},
            {fields: ["cocurricular_details"], trigger: "cocurricular_activities", values: ["1"]},
            {fields: ["idp_status_id"], trigger: "is_refugee", values: ["1"]},
            {fields: ["is_registered_refugee"], trigger: "is_refugee", values: ["1"]},
            {fields: ["refugee_card_number"], trigger: "is_registered_refugee", values: ["1"]},
            {fields: ["disability_types[]"], trigger: "has_major_disability", values: ["1"]},
            {fields: ["mental_disability_type"], trigger: "has_mental_disability", values: ["1"]},
            {fields: ["glass_prescription"], trigger: "visually_fit", values: ["0"]},
            {fields: ["bus_route"], trigger: "transport_facility", values: ["Bus", "Institution Bus"]},
            {fields: ["digital_device_type[]"], trigger: "digital_device_at_home", values: ["1"]},
            {fields: ["emergency_relation_other"], trigger: "emergency_relation", values: ["Other", "Others"]},
            {fields: ["guardian_relation_other"], trigger: "guardian_relation", values: ["Other"]},
            {fields: ["father_contact"], trigger: "is_father_alive", values: ["1"]},
            {fields: ["mother_contact"], trigger: "is_mother_alive", values: ["1"]},
            {fields: ["mother_bps"], trigger: "mother_profession", values: ["Govt Employee"]},
            {fields: ["girls_stipend"], trigger: "gender", values: ["Female"]},
            {fields: ["guardian_name", "guardian_cnic", "guardian_relation", "guardian_contact", "guardian_profession", "guardian_income"], trigger: "is_father_alive", values: ["0"]},
        ];
        conditionalRequired.forEach(function (cr) {
            // Trigger may be a radio group or a <select> (e.g. mother_profession)
            var triggerVal = null;
            var trigSel = pane.querySelector('select[name="' + cr.trigger + '"]');
            if (trigSel) {
                triggerVal = trigSel.value;
            } else {
                var triggerRadio = pane.querySelector('input[name="' + cr.trigger + '"]:checked');
                triggerVal = triggerRadio ? triggerRadio.value : null;
            }
            if (triggerVal === null || triggerVal === "" || cr.values.indexOf(triggerVal) < 0) return;
            cr.fields.forEach(function (fname) {
                var ctl = fieldControl(pane, fname);
                if (!ctl) return;
                if (isHiddenWithin(pane, ctl.els[0])) return;
                if (!controlValue(ctl)) {
                    var labelText = fieldLabel(pane, fname);
                    if (missing.indexOf(labelText) < 0) missing.push(labelText);
                }
            });
        });

        // Mother Income: mandatory unless profession = Housewife (§8).
        // Skips entirely when either control's group is hidden (8.3 dead zone).
        var motherProf = pane.querySelector('select[name="mother_profession"]');
        var motherIncome = pane.querySelector('select[name="mother_monthly_income"]');
        if (motherProf && motherIncome &&
            !isHiddenWithin(pane, motherProf) && !isHiddenWithin(pane, motherIncome)) {
            var mp = (motherProf.value || "").trim().toLowerCase();
            if (mp && mp !== "housewife" && !motherIncome.value) {
                missing.push("Mother's Income (per month)");
            }
        }

        // Orphan Yes not allowed if both parents alive
        var orphanYes = pane.querySelector('input[name="is_orphan"]:checked');
        if (orphanYes && orphanYes.value === "1") {
            var fa = pane.querySelector('input[name="is_father_alive"]:checked');
            var ma = pane.querySelector('input[name="is_mother_alive"]:checked');
            if (fa && fa.value === "1" && ma && ma.value === "1") {
                missing.push("Is Orphan (not allowed when both parents are alive)");
            }
        }

        if (missing.length > 0) {
            alert("Tab " + (tabIndex + 1) + " — please fill the following mandatory fields:\n\n• " + missing.join("\n• "));
            return false;
        }
        return true;
    }

    // ==================================================================
    // SAVE & NEXT / SUBMIT — AJAX
    // ==================================================================
    if (saveNextBtn) {
        saveNextBtn.addEventListener("click", function () {
            var isLastTab = currentTab >= 6;
            if (isLastTab) {
                // Final submit validates EVERY tab: FEMIS requires the full
                // record at submit, and jumping tabs never validated the ones
                // skipped along the way (§8-8.2).
                for (var t = 0; t < tabIds.length; t++) {
                    if (!validateTab(t, document.getElementById(tabIds[t]))) return;
                }
            } else if (!validateTab(currentTab)) {
                return;
            }

            var data = {};
            var activeTab = document.querySelector(".tab-pane.active");
            if (!activeTab) return;

            // Collect all form fields from active tab (include present_* even when
            // the permanent block is hidden by "Same as Temporary Address")
            var fields = activeTab.querySelectorAll("input, select, textarea");
            var arrayChecks = {};
            fields.forEach(function (f) {
                var isPresentAddr = f.name && f.name.indexOf("present_") === 0;
                if (f.offsetParent === null && f.type !== "hidden" && !isPresentAddr) return;
                if (f.type === "radio") {
                    if (f.checked) data[f.name] = f.value;
                } else if (f.type === "checkbox") {
                    if (f.name && f.name.slice(-2) === "[]") {
                        if (!arrayChecks[f.name]) arrayChecks[f.name] = [];
                        if (f.checked) arrayChecks[f.name].push(f.value);
                    } else {
                        data[f.name] = f.checked ? (f.value || "1") : "";
                    }
                } else if (f.tagName === "SELECT") {
                    data[f.name] = f.value;
                } else {
                    data[f.name] = f.value;
                }
            });
            Object.keys(arrayChecks).forEach(function (n) {
                data[n] = arrayChecks[n].join(",");
            });

            // Also collect all hidden fields in the form
            document.querySelectorAll("#admissionForm input[type='hidden']").forEach(function (f) {
                data[f.name] = f.value;
            });

            var endpoint = isLastTab ? "/api/final-submit" : "/api/save-tab";
            var payload = isLastTab
                ? { student_id: studentId.value, data: data }
                : { tab: currentTab + 1, student_id: studentId.value || null, data: data };

            saveNextBtn.disabled = true;
            saveNextBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

            fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                saveNextBtn.disabled = false;
                if (!res.ok) {
                    alert("Error saving: " + (res.error || "Unknown error"));
                    saveNextBtn.innerHTML = '<i class="bi bi-save me-2"></i><span id="btn-label">' + btnLabel.textContent + '</span> <i id="btn-arrow" class="bi ' + btnArrow.className.replace('bi ', '') + ' ms-1"></i>';
                    return;
                }

                if (!isLastTab && res.student_id) {
                    studentId.value = res.student_id;
                }

                // Upload any file inputs on this tab
                var fileInputs = activeTab.querySelectorAll('input[type="file"]');
                var uploadPromises = [];
                fileInputs.forEach(function (fi) {
                    if (fi.files.length > 0 && studentId.value) {
                        var fd = new FormData();
                        fd.append("student_id", studentId.value);
                        fd.append("field_name", fi.name);
                        fd.append(fi.name, fi.files[0]);
                        uploadPromises.push(
                            fetch("/api/upload-file", { method: "POST", body: fd })
                                .then(function (r) { return r.json(); })
                        );
                    }
                });

                Promise.all(uploadPromises).then(function () {
                    markClean();
                    if (isLastTab) {
                        window.location.href = "/success/" + res.student_id;
                    } else {
                        var nextTab = tabPills[currentTab + 1];
                        if (nextTab) {
                            bootstrap.Tab.getOrCreateInstance(nextTab).show();
                        }
                    }
                }).catch(function () {
                    markClean();
                    if (isLastTab) {
                        window.location.href = "/success/" + res.student_id;
                    } else {
                        var nextTab = tabPills[currentTab + 1];
                        if (nextTab) {
                            bootstrap.Tab.getOrCreateInstance(nextTab).show();
                        }
                    }
                });
            })
            .catch(function (err) {
                saveNextBtn.disabled = false;
                alert("Network error: " + err.message);
                saveNextBtn.innerHTML = '<i class="bi bi-save me-2"></i><span id="btn-label">' + btnLabel.textContent + '</span>';
            });
        });
    }

    // ==================================================================
    // FORM PRE-FILL (edit mode)
    // ==================================================================
    if (studentId && studentId.value) {
        fetch("/students/" + studentId.value + "/json")
            .then(function (r) { return r.json(); })
            .then(function (s) {
                var reverseMap = {
                    "is_bform_available": "is_bform_available", "b_form": "b_form",
                    "is_father_alive": "is_father_alive", "is_mother_alive": "is_mother_alive",
                    "is_orphan": "is_orphan", "father_monthly_income": "father_monthly_income",
                    "class_id": "class_id", "section_id": "section_id",
                    "last_class_result": "result_percentage",
                    "last_fde_institution_id": "last_fde_institution_id",
                    "last_institution_other": "last_other_institution",
                    "class_admitted_id": "class_admitted_id",
                    "school_meal_program_availing": "school_meal_program_availing",
                    "is_hafiz": "is_hafiz",                     "siblings_same": "siblings_same_institution",
                    "cocurricular_activities": "cocurricular_activities",
                    "emergency_name": "emergency_name",
                    "emergency_contact": "emergency_contact",
                    "is_refugee": "is_refugee",
                    "is_registered_refugee": "is_registered_refugee",
                    "refugee_card": "refugee_card_number",
                    "transport": "transport_facility",
                    "has_major_disability": "has_major_disability",
                    "has_mental_disability": "has_mental_disability",
                    "other_medical_condition": "other_medical_condition",
                    "uses_glasses": "uses_glasses",
                    "has_hearing_difficulties": "has_hearing_difficulties",
                    "digital_device_at_home": "digital_device_at_home",
                    "digital_device_type": "digital_device_type[]",
                    "internet_at_home": "internet_at_home",
                    "roll_no": "roll_no",
                    "sector_id": "sector_id", "village_id": "village_id",
                    "sub_sector_id": "sub_sector_id",
                    "housing_society_id": "housing_society_id",
                    "nationality_id": "nationality_id",
                    "religion_id": "religion_id",
                    "language_id": "language_id",
                    "city_id": "city_id",
                    "same_as_permanent_address": "same_as_permanent_address",
                    "house": "house", "street": "street",
                    "domicile_province_id": "domicile_province_id",
                    "domicile_district_id": "domicile_district_id",
                    "father_domicile_province_id": "father_domicile_province_id",
                    "father_domicile_district_id": "father_domicile_district_id",
                    "disability_types": "disability_types[]",
                    "major_disability_text": "major_disability_text",
                    "father_profession_other": "father_profession_other",
                    "mother_profession_other": "mother_profession_other",
                    "guardian_profession_other": "guardian_profession_other",
                    "guardian_relation_other": "guardian_relation_other",
                    "guardian_email": "guardian_email",
                    "mother_language_other": "mother_language_other",
                    "emergency_relation_other": "emergency_relation_other",
                    "mental_disability_other": "mental_disability_other",
                    "glass_prescription": "glass_prescription",
                    "hearing_aid_details": "hearing_aid_details",
                    "present_sector_id": "present_sector_id",
                    "present_sub_sector_id": "present_sub_sector_id",
                    "present_village_id": "present_village_id",
                    "present_housing_society_id": "present_housing_society_id",
                    "primary_education_completion_years": "primary_education_completion_years",
                    "class_group_id": "class_group_id",
                    "present_house": "present_house",
                    "present_street": "present_street",
                    "present_address_type": "present_address_type",
                    "achievement_details": "cocurricular_details",
                    "address_other": "address",
                    "present_address_other": "present_address",
                };

                Object.keys(s).forEach(function (dbCol) {
                    var val = s[dbCol];
                    if (val === null || val === undefined || val === "") return;
                    var formName = reverseMap[dbCol] || dbCol;

                    // Try select
                    var sel = document.querySelector('select[name="' + formName + '"]');
                    if (sel) {
                        sel.value = val;
                        if (String(sel.value) !== String(val)) {
                            sel.setAttribute("data-pending-value", val);
                        }
                        sel.dispatchEvent(new Event("change"));
                        return;
                    }

                    // Try radio
                    var radio = document.querySelector('input[name="' + formName + '"][value="' + val + '"]');
                    if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change")); return; }

                    if (formName.slice(-2) === "[]") {
                        var checks = document.querySelectorAll('input[type="checkbox"][name="' + formName + '"]');
                        if (checks.length) {
                            var wanted = String(val).split(",").map(function (x) { return x.trim(); }).filter(Boolean);
                            checks.forEach(function (cb) { cb.checked = wanted.indexOf(cb.value) >= 0; });
                            checks[0].dispatchEvent(new Event("change"));
                            return;
                        }
                    }

                    // Try input
                    var input = document.querySelector('[name="' + formName + '"]');
                    if (input) {
                        if (input.type !== "radio" && input.type !== "checkbox") {
                            input.value = val;
                        }
                        input.dispatchEvent(new Event("change"));
                    }
                });

                markClean();
            })
            .catch(function () {});
    }

    // ==================================================================
    // Auto-scroll on tab switch
    // ==================================================================
    tabPills.forEach(function (link) {
        link.addEventListener("shown.bs.tab", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    });
});
