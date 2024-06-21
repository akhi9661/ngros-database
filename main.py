import customtkinter as ctk, tkinter as tk, numpy as np
from tkinter import scrolledtext, filedialog, messagebox, ttk, Toplevel, simpledialog, Label
import platform, os, shutil, rasterio
import pandas as pd
from collections import defaultdict
import tkinter.font as tkfont
import geopandas as gpd, matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from rasterio.plot import show
from matplotlib.figure import Figure
import mplcursors
from matplotlib.lines import Line2D
import requests
from datetime import datetime
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading, queue

# Directory paths
DATABASE_FOLDER = "database"
SHP_PATH = os.path.join("backend_datasets", 'australia.shp')
BASEMAP_PATH = os.path.join( "backend_datasets", 'australia_basemap_wgs84.TIF')
SITE_LIST_FILE = os.path.join(DATABASE_FOLDER, "site_list.csv")
SITE_FILES_FOLDER = os.path.join(DATABASE_FOLDER, "site_files")
display_selection = None

os.makedirs(SITE_FILES_FOLDER, exist_ok=True)
if not os.path.exists(SITE_LIST_FILE):
    pd.DataFrame(columns=["Serial No.", "File Name", "Site ID", "Latitude", "Longitude"]).to_csv(SITE_LIST_FILE, index=False)

# Functions
def load_site_list():
    if os.path.exists(SITE_LIST_FILE):
        df = pd.read_csv(SITE_LIST_FILE)
        out_text.delete(1.0, ctk.END)
        out_text.insert(ctk.END, df.to_string(index=False))
        out_text.insert(ctk.END, "\n")
        checkbox_event()
    else:
        out_text.insert(ctk.END, "No sites uploaded yet.\n")

def parse_date(date_str):
    if isinstance(date_str, datetime):
        return date_str
    
    for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Date {date_str} is not in an expected format.")

def fetch_api_data(api_url):
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            return response.text
        else:
            return None
    except Exception as e:
        print(f"Error fetching data from API: {e}")
        return None

# Define the function to fetch and update data
def fetch_and_update_data(selected_file, progress_var, status_label, gui_queue):
    # Path to the site file
    site_file_path = os.path.join(SITE_FILES_FOLDER, selected_file)
    
    if not os.path.exists(site_file_path):
        gui_queue.put((status_label, f"File {selected_file} not found."))
        return

    site_data_df = pd.read_csv(site_file_path)
    
    # Read the site list CSV to get coordinates
    site_list_path = SITE_LIST_FILE
    site_df = pd.read_csv(site_list_path)
    
    # Extract site information
    site_name = os.path.basename(selected_file)
    gui_queue.put((status_label, f"Processing site: {site_name}"))
    site_info = site_df[site_df['File Name'] == site_name]
    
    if site_info.empty:
        gui_queue.put((status_label, f"Coordinates for site {site_name} not found."))
        return
    
    latitude = site_info.iloc[0]['Latitude']
    longitude = site_info.iloc[0]['Longitude']
    
    # Ensure date and hour columns are extracted from local_time
    #site_data_df['local_time'] = pd.to_datetime(site_data_df['local_time'])
    site_data_df['local_time'] = site_data_df['local_time'].apply(parse_date)
    site_data_df['date'] = site_data_df['local_time'].dt.strftime("%Y%m%d")
    site_data_df['hour'] = site_data_df['local_time'].dt.hour
    
    unique_dates = site_data_df['date'].unique()
    
    gui_queue.put((progress_var, 0))
    total_steps = len(unique_dates)
    
    api_responses = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        future_to_date = {}
        for date in unique_dates:
            start_day = date
            end_day = date
            api_url = f"https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=PRECTOTCORR,T2M,RH2M,WS2M,ALLSKY_SFC_SW_DWN&community=AG&longitude={longitude}&latitude={latitude}&start={start_day}&end={end_day}&format=CSV"
            future = executor.submit(fetch_api_data, api_url)
            future_to_date[future] = date
        
        for step, future in enumerate(as_completed(future_to_date)):
            date = future_to_date[future]
            response_text = future.result()
            if response_text:
                api_responses.append((date, response_text))
            else:
                gui_queue.put((status_label, f"Failed to fetch data for {site_name} on {date}"))
            
            # Update progress bar and status label
            gui_queue.put((progress_var, (step + 1) / total_steps * 100))
            gui_queue.put((status_label, f"Fetched data for date: {date} ({step + 1}/{total_steps})"))

    gui_queue.put((status_label, f"Processing fetched data: Matching hourly records."))
    # Process the fetched data using a batch update
    updates = {'PRECTOTCORR': [], 'T2M': [], 'RH2M': [], 'WS2M': [], 'ALLSKY_SFC_SW_DWN': []}
    for date, response_text in api_responses:
        api_data_df = pd.read_csv(StringIO(response_text), skiprows=13)
        api_data_df['date'] = date
        for hour in range(24):
            matching_rows = api_data_df[api_data_df['HR'] == hour]
            if not matching_rows.empty:
                for param in updates.keys():
                    updates[param].append((date, hour, matching_rows[param].values[0]))

    for param, values in updates.items():
        for date, hour, value in values:
            mask = (site_data_df['date'] == date) & (site_data_df['hour'] == hour)
            site_data_df.loc[mask, param] = value

    # Save the updated CSV file
    site_data_df.drop(columns=['date', 'hour'], inplace=True)
    site_data_df.to_csv(site_file_path, index=False)
    gui_queue.put((status_label, f"Updated data for {selected_file}"))
    gui_queue.put((progress_var, 100))
    gui_queue.put(('messagebox', "Success", f"Data update for {selected_file} completed successfully."))
    gui_queue.put(('callback', display_table))
    gui_queue.put(('callback', checkbox_event))

def gui_update(gui_queue):
    try:
        while True:
            task = gui_queue.get_nowait()
            if isinstance(task, tuple):
                if task[0] == 'messagebox':
                    messagebox.showinfo(task[1], task[2])
                elif task[0] == 'callback':
                    task[1]()
                else:
                    widget, value = task
                    if isinstance(widget, ttk.Progressbar):
                        widget['value'] = value
                    elif isinstance(widget, tk.Variable):
                        widget.set(value)
                    elif isinstance(widget, Label):
                        widget.config(text=value)
    except queue.Empty:
        pass
    root.after(100, gui_update, gui_queue)

def on_update(selected_file, input_frame):
    # Progress bar and status label
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(input_frame, variable=progress_var, maximum=100)
    progress_bar.grid(row=6, column=0, columnspan=2, sticky='nsew', padx=5, pady=5)
    
    status_label = Label(input_frame, text="", anchor='w', font=('Calibri', 12))
    status_label.grid(row=7, column=0, columnspan=2, sticky='nsew', padx=5, pady=5)
    
    gui_queue = queue.Queue()
    threading.Thread(target=fetch_and_update_data, args=(selected_file, progress_var, status_label, gui_queue)).start()
    root.after(100, gui_update, gui_queue)
    
def display_table():
    for widget in display_frame.winfo_children():
        widget.destroy()

    def calculate_averages(df, columns):
        averages = df[columns].mean().to_dict()
        rounded_averages = {col: round(avg, 3) for col, avg in averages.items()}
        return rounded_averages

    def process_site_files(entries, site_files_columns):
        averages_list = []
        for entry in entries:
            file_name = entry['File Name']
            file_path = os.path.join(SITE_FILES_FOLDER, file_name)
            df = pd.read_csv(file_path)
            df = df.drop(columns=['entity_id', 'local_time'])
            unnamed_columns = [col for col in df.columns if col.startswith('Unnamed:')]
            if unnamed_columns:
                # Ensure columns exist in the DataFrame before attempting to drop them
                unnamed_columns_to_drop = [col for col in unnamed_columns if col in df.columns]
                df = df.drop(columns=unnamed_columns_to_drop, axis=1)
                site_files_columns = df.columns
            averages = calculate_averages(df, site_files_columns)
            averages_list.append(averages)
            entry.update(averages)
        return averages_list

    def on_select(event):
        child_site_frame = ctk.CTkFrame(display_frame)
        child_site_frame.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        child_site_frame.grid_rowconfigure(0, weight=1)
        child_site_frame.grid_columnconfigure(0, weight=1)

        # Adding scrollbars
        child_x_scrollbar = ttk.Scrollbar(child_site_frame, orient="horizontal")
        child_y_scrollbar = ttk.Scrollbar(child_site_frame, orient="vertical")

        item_id = table.identify_row(event.y)
        if item_id:
            site_id = table.item(item_id, 'values')[2]

            # Filter entries for the selected site_id
            entries = site_entries[site_id]

            # Determine all columns dynamically
            base_columns = list(entries[0].keys())
            temp_df = pd.read_csv(os.path.join(SITE_FILES_FOLDER, table.item(item_id, 'values')[1]))
            site_files_columns = list(temp_df.drop(columns=['entity_id', 'local_time']).columns)
            #['drip_rate', 'PRECTOTCORR', 'T2M', 'RH2M', 'WS2M', 'ALLSKY_SFC_SW_DWN']

            # Process site files to get averages
            averages_list = process_site_files(entries, site_files_columns)

            # Display entries in child_site_frame as Treeview
            style = ttk.Style()
            style.configure("mystyle.Treeview", highlightthickness=0, bd=0, font=('Calibri', 13))
            style.configure("mystyle.Treeview.Heading", font=('Calibri', 13, 'bold'))
            style.layout("mystyle.Treeview", [('mystyle.Treeview.treearea', {'sticky': 'nswe'})])

            all_columns = base_columns + site_files_columns
            child_table = ttk.Treeview(child_site_frame, columns=all_columns, show='headings', style="mystyle.Treeview",
                                       xscrollcommand=child_x_scrollbar.set, yscrollcommand=child_y_scrollbar.set)
            for col in all_columns:
                child_table.heading(col, text=col, anchor='nw')
                child_table.column(col, width=25)
                child_table.column("#0", width=15)

            for entry, averages in zip(entries, averages_list):
                row_values = [entry.get(col, "") for col in base_columns]
                row_values += [averages.get(col, "") for col in site_files_columns]
                child_table.insert("", "end", values=row_values)

            child_table.bind("<Double-1>", on_double_click) # Select and Double-click opens up file in default system app
            child_table.bind("<Delete>", delete_items) # Select and press Delete prompts (& executes) deletion
            child_table.bind("<Return>", lambda event: display_file(child_table)) # Select and press Enter opens up file inside GUI

            child_x_scrollbar.config(command=child_table.xview)
            child_y_scrollbar.config(command=child_table.yview)
            child_x_scrollbar.pack(side="bottom", fill="x")
            child_y_scrollbar.pack(side="right", fill="y")

            # Configure Treeview and pack it into child_site_frame
            child_table.pack(expand=True, fill='both')

    def display_file(treeview):
        result_window = ctk.CTkToplevel(root)
        result_window.geometry('800x600+50+50') 
    
        result_frame = ctk.CTkFrame(result_window)
        result_frame.pack(expand=True, fill='both')
    
        # Adding scrollbars
        x_scrollbar = ttk.Scrollbar(result_frame, orient="horizontal")
        y_scrollbar = ttk.Scrollbar(result_frame, orient="vertical")
    
        selected_item = treeview.selection()
        if selected_item:
            file_name = treeview.item(selected_item)['values'][1]  # Assuming 'File Name' is the second column
            result_window.title(f"{file_name.split('.')[0]}")
            if file_name:
                file_path = os.path.join(SITE_FILES_FOLDER, file_name)
                df = pd.read_csv(file_path)
                unnamed_columns = [col for col in df.columns if col.startswith('Unnamed:')]
                df = df.drop(columns=unnamed_columns, axis=1)
    
                num_rows = len(df.index)
                count_label = ctk.CTkLabel(result_window, text=f"Showing {num_rows} rows")
                count_label.pack()
    
                columns = list(df.columns)
    
                style = ttk.Style()
                style.configure("mystyle.Treeview", highlightthickness=0, bd=0, font=('Calibri', 13))
                style.configure("mystyle.Treeview.Heading", font=('Calibri', 13, 'bold'))
                style.layout("mystyle.Treeview", [('mystyle.Treeview.treearea', {'sticky': 'nswe'})])
                result_table = ttk.Treeview(result_frame, columns=columns, show='headings', style="mystyle.Treeview",
                                            xscrollcommand=x_scrollbar.set, yscrollcommand=y_scrollbar.set)
                for col in columns:
                    result_table.heading(col, text=col, anchor='nw')
                    result_table.column(col, stretch=True, width=100)
    
                # Insert data rows into the Treeview
                for index, row in df.iterrows():
                    result_table.insert('', 'end', values=list(row))
    
                x_scrollbar.configure(command=result_table.xview)
                y_scrollbar.configure(command=result_table.yview)
                x_scrollbar.pack(side="bottom", fill="x")
                y_scrollbar.pack(side="right", fill="y")
    
                result_table.pack(expand=True, fill='both')
        
    parent_site_frame = ctk.CTkFrame(display_frame)
    parent_site_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    parent_site_frame.grid_rowconfigure(0, weight=1)
    parent_site_frame.grid_columnconfigure(0, weight=1)

    # Adding scrollbars
    parent_x_scrollbar = ttk.Scrollbar(parent_site_frame, orient="horizontal")
    parent_y_scrollbar = ttk.Scrollbar(parent_site_frame, orient="vertical")

    if os.path.exists(SITE_LIST_FILE):
        df = pd.read_csv(SITE_LIST_FILE)
        columns = list(df.columns)
        site_files_columns = ['drip_rate', 'PRECTOTCORR', 'T2M', 'RH2M', 'WS2M', 'ALLSKY_SFC_SW_DWN']
        all_columns = columns + site_files_columns

        global site_entries
        site_entries = defaultdict(list)
        for index, row in df.iterrows():
            site_id = row['Site ID']
            site_entries[site_id].append(row)

        # Update parent_site_frame table to include all columns with averages
        all_columns = columns + ['Averages'] + site_files_columns

        global table
        style = ttk.Style()
        style.configure("mystyle.Treeview", highlightthickness=0, bd=0, font=('Calibri', 13))
        style.configure("mystyle.Treeview.Heading", font=('Calibri', 13, 'bold'))
        style.layout("mystyle.Treeview", [('mystyle.Treeview.treearea', {'sticky': 'nswe'})])

        table = ttk.Treeview(parent_site_frame, columns=columns, show='headings', style="mystyle.Treeview",
                             xscrollcommand=parent_x_scrollbar.set, yscrollcommand=parent_y_scrollbar.set)
        for col in columns:
            table.heading(col, text=col, anchor='nw')
            table.column(col, width=25)
            table.column("#0", width=15)

        for site_id, entries in site_entries.items():
            first_entry = entries[0]
            row_values = [first_entry.get(col, "") for col in columns]
            # Insert main row for each unique Site ID
            table.insert("", "end", values=row_values)

        table.bind("<ButtonRelease-1>", on_select)
        table.bind("<Delete>", delete_items)

        parent_x_scrollbar.config(command=table.xview)
        parent_y_scrollbar.config(command=table.yview)
        parent_x_scrollbar.pack(side="bottom", fill="x")
        parent_y_scrollbar.pack(side="right", fill="y")

        table.pack(expand=True, fill='both')
        checkbox_event()

def on_double_click(event):
    item_id = table.identify_row(event.y)
    item_values = table.item(item_id, 'values')
    site_name = item_values[1]  # Assuming second column is the File Name
    site_path = os.path.join(SITE_FILES_FOLDER, site_name)
    if os.path.exists(site_path):
        open_site_file(site_path)
    else:
        messagebox.showerror("File Not Found", f"The file {site_name} does not exist.")

def delete_items(event):
    selected_items = table.selection()
    if not selected_items:
        return
    
    if messagebox.askyesno("Confirm Deletion", "Are you sure you want to delete the selected item(s)?"):
        for item_id in selected_items:
            item_values = table.item(item_id, 'values')
            site_name = item_values[1]  # Assuming second column is the File Name
            site_id = item_values[2]
            table.delete(item_id)
            delete_site_files(site_name, site_id)

def delete_site_files(site_name, site_id):
    site_file_path = os.path.join(SITE_FILES_FOLDER, site_name)
    try:
        os.remove(site_file_path)
        out_text.insert(ctk.END, f"Deleted file: {site_file_path} with Site ID: [{site_id}]\n")
    except FileNotFoundError:
        out_text.insert(ctk.END, f"File not found: {site_file_path}\n")
    except Exception as e:
        out_text.insert(ctk.END, f"Error deleting file: {site_file_path}, {e}\n")

    # Remove from site list CSV
    if os.path.exists(SITE_LIST_FILE):
        df = pd.read_csv(SITE_LIST_FILE)
        df = df[df['File Name'] != site_name]
        df.to_csv(SITE_LIST_FILE, index=False)
        out_text.insert(ctk.END, f"Deleted Site ID: {site_id}\n")

    load_site_list()
    checkbox_event()

def open_site_file(file_path):
    if platform.system() == "Windows":
        os.startfile(file_path)
    elif platform.system() == "Darwin":  # macOS
        os.system(f"open {file_path}")
    elif platform.system() == "Linux":
        os.system(f"xdg-open {file_path}")
    else:
        messagebox.showerror("Unsupported OS", "Cannot open file on this operating system.")

def get_site_info(parent):
    # Load existing site data
    df = pd.read_csv(SITE_LIST_FILE)
    existing_site_ids = df['Site ID'].unique()

    # Function to autofill the entries based on selected site ID
    def autofill(event):
        selected_site_id = site_id_box.get()
        if selected_site_id in existing_site_ids:
            site_data = df[df['Site ID'] == selected_site_id].iloc[0]
            site_id_entry.delete(0, ctk.END)
            site_id_entry.insert(0, site_data['Site ID'])
            latitude_entry.delete(0, ctk.END)
            latitude_entry.insert(0, site_data['Latitude'])
            longitude_entry.delete(0, ctk.END)
            longitude_entry.insert(0, site_data['Longitude'])

    dialog = ctk.CTkToplevel(parent)
    dialog.geometry('300x250+50+50')
    dialog.title("Enter Site Information")
    
    # Define result as None initially
    result = None
    
    # Combobox for selecting existing site IDs
    ctk.CTkLabel(dialog, text="Select Site ID:").grid(row=0, column=0, padx=10, pady=5)
    site_id_box = ctk.CTkComboBox(dialog, values=existing_site_ids, command = autofill)
    site_id_box.grid(row=0, column=1, padx=10, pady=5)
    site_id_box.set("Select an option")
    
    # Labels and Entry fields for Site ID, Latitude, and Longitude
    ctk.CTkLabel(dialog, text="Site ID:").grid(row=1, column=0, padx=10, pady=5)
    site_id_entry = ctk.CTkEntry(dialog)
    site_id_entry.grid(row=1, column=1, padx=10, pady=5)
    
    ctk.CTkLabel(dialog, text="Latitude:").grid(row=2, column=0, padx=10, pady=5)
    latitude_entry = ctk.CTkEntry(dialog)
    latitude_entry.grid(row=2, column=1, padx=10, pady=5)
    
    ctk.CTkLabel(dialog, text="Longitude:").grid(row=3, column=0, padx=10, pady=5)
    longitude_entry = ctk.CTkEntry(dialog)
    longitude_entry.grid(row=3, column=1, padx=10, pady=5)
    
    # site_id_box.bind("<<ComboboxSelected>>", autofill)
    
    # Function to handle OK button click
    def ok():
        nonlocal result  # Access the outer 'result' variable
        site_id = site_id_entry.get()
        latitude = latitude_entry.get()
        longitude = longitude_entry.get()
        
        if not site_id or not latitude or not longitude:
            messagebox.showerror("Error", "Please enter all fields.")
        else:
            result = (site_id, latitude, longitude)
            dialog.destroy()
    
    # OK and Cancel buttons
    ok_button = ctk.CTkButton(dialog, text="OK", command=ok)
    ok_button.grid(row=4, column=0, columnspan=2, pady=10)
    
    cancel_button = ctk.CTkButton(dialog, text="Cancel", command=dialog.destroy)
    cancel_button.grid(row=5, column=0, columnspan=2, pady=10)
    
    # Focus on the first entry field
    site_id_entry.focus_set()
    
    # Run the dialog in modal mode
    dialog.transient(parent)
    dialog.grab_set()
    parent.wait_window(dialog)
    
    return result
    
def add_site():
    file_path = filedialog.askopenfilename( parent=root, filetypes=[("CSV files", "*.csv"), ("Excel files", "*.xlsx")])
    if file_path:
        site_name = os.path.basename(file_path)
        new_site_path = os.path.join(SITE_FILES_FOLDER, site_name)
        shutil.copy(file_path, new_site_path)
        
        # Get Site ID, Latitude, and Longitude from the user
        site_info = get_site_info(root)
        
        if site_info:
            site_id, latitude, longitude = site_info
            
            # Update the CSV with the new site information
            df = pd.read_csv(SITE_LIST_FILE)
            new_row = pd.DataFrame({"Serial No.": [len(df)+1],
                                    "File Name": [site_name],
                                    "Site ID": [site_id],
                                    "Latitude": [latitude],
                                    "Longitude": [longitude]})
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(SITE_LIST_FILE, index=False)
            
            load_site_list()
            checkbox_event()
            if display_selection == 'Table':
                display_table()
            elif display_selection == 'Map':
                display_map()
            messagebox.showinfo("Success", f"Site '{site_name}' uploaded successfully!")

def export_site():
    export_path = filedialog.askdirectory()
    if export_path:
        destination = os.path.join(export_path, "database")
        if os.path.exists(destination):
            shutil.rmtree(destination)
        shutil.copytree(DATABASE_FOLDER, destination)
        messagebox.showinfo("Success", f"Database exported successfully to '{destination}'")

def on_combobox_select(*args):
    global display_selection
    display_selection = display_var.get()
    if display_selection == "Table": 
        display_table()
        
    elif display_selection == "Map":
        display_map()

def display_map():
    root.geometry(f"{window_width+250}x{window_height}+{x_position}+{y_position}")
    
    # Clear previous content in display_frame
    for widget in display_frame.winfo_children():
        widget.destroy()

    canvas_frame_map = ctk.CTkFrame(display_frame)
    canvas_frame_map.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    canvas_frame_map.grid_rowconfigure(0, weight=1)
    canvas_frame_map.grid_columnconfigure(0, weight=1)

    if os.path.exists(SITE_LIST_FILE):
        df = pd.read_csv(SITE_LIST_FILE)

        # Create a GeoDataFrame
        if not df.empty:
            gdf = gpd.GeoDataFrame(
                df, 
                geometry=gpd.points_from_xy(df.Longitude, df.Latitude)
            )

            # Plotting using matplotlib
            fig, ax = plt.subplots(figsize=(10, 6))
            australia = gpd.read_file(SHP_PATH)
            
            try:
                with rasterio.open(BASEMAP_PATH) as src:
                    fig = Figure(figsize=(8, 5), dpi=110)
                    ax = fig.add_subplot(111)
                    show(src, ax=ax)
                    ax.set_title("NGROS Sites")
                    canvas = FigureCanvasTkAgg(fig, master=canvas_frame_map)
                    canvas.draw()
                    canvas.get_tk_widget().grid(row=0, column=0, sticky='nsew')
    
                    # Add the Matplotlib toolbar for zoom and pan
                    toolbar_frame = tk.Frame(canvas_frame_map)
                    toolbar_frame.grid(row=1, column=0, sticky='nsew')
                    toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
                    toolbar.update()
                    toolbar.pack(side=ctk.TOP, fill=ctk.X)
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")

            gdf.plot(ax=ax, color='red', markersize=50)
            australia.boundary.plot(ax=ax, linewidth=0.5, linestyle=':', alpha=0.8, color='black')

            # Add site ID labels
            for x, y, label in zip(gdf.geometry.x, gdf.geometry.y, gdf['Site ID']):
                ax.text(x, y, label, fontsize=8, ha='right')

            # Add mplcursors for interactivity
            cursor = mplcursors.cursor(ax.collections[0], hover=mplcursors.HoverMode.Transient)

            @cursor.connect("add")
            def on_add(sel):
                index = sel.index
                info = gdf.iloc[index]
                text = '\n'.join(f"{col}: {info[col]}" for col in gdf.columns if col not in ['geometry', 'Serial No.', 'File Name'])
                sel.annotation.set(text=text)
                sel.annotation.get_bbox_patch().set_alpha(0.8)

            @cursor.connect("remove")
            def on_remove(sel):
                sel.annotation.set_visible(False)
                sel.annotation.set_text('')

        else:
            messagebox.showinfo("No Sites", "No sites available to display on the map.")
    else:
        messagebox.showerror("File Not Found", "The site list file does not exist.")

    canvas_frame_graph = ctk.CTkFrame(display_frame)
    canvas_frame_graph.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    canvas_frame_graph.grid_rowconfigure(0, weight=1)
    canvas_frame_graph.grid_columnconfigure(0, weight=1)
    
    graph_frame = ctk.CTkFrame(canvas_frame_graph)
    graph_frame.grid(row=0, sticky='nsew', padx=5, pady=2)
    plot_frame = ctk.CTkFrame(canvas_frame_graph)
    plot_frame.grid(row=1, sticky='nsew', padx=5, pady=2)
    
    canvas_frame_graph.grid_rowconfigure(0, weight=1)
    canvas_frame_graph.grid_rowconfigure(1, weight=3)

    display_graph(graph_frame, plot_frame)

def display_graph(graph_frame, plot_frame):
    # Clear previous content in graph_frame
    for widget in graph_frame.winfo_children():
        widget.destroy()

    for widget in plot_frame.winfo_children():
        widget.destroy()

    # Load site list DataFrame
    if os.path.exists(SITE_LIST_FILE):
        df = pd.read_csv(SITE_LIST_FILE)
    else:
        messagebox.showerror("Error", f"Site list file {SITE_LIST_FILE} does not exist.")
        return

    # Create Comboboxes
    site_id_label = ctk.CTkLabel(graph_frame, text="Select Site ID:", font=('Calibri', 13))
    site_id_label.grid(row=0, column=0, padx=10, pady=10, sticky='w')
    site_id_combobox = ttk.Combobox(graph_frame, state="readonly")
    site_id_combobox.grid(row=0, column=1, padx=10, pady=10, sticky='w')

    parameter_label = ctk.CTkLabel(graph_frame, text="Select Parameter:", font=('Calibri', 13))
    parameter_label.grid(row=1, column=0, padx=10, pady=10, sticky='w')
    parameter_combobox = ttk.Combobox(graph_frame, state="readonly")
    parameter_combobox.grid(row=1, column=1, padx=10, pady=10, sticky='w')

    # Load unique site IDs into site_id_combobox
    site_id_combobox['values'] = df['Site ID'].unique().tolist()

    # Function to update parameter combobox based on selected site ID
    def update_parameters(*args):
        selected_site_id = site_id_combobox.get()
        if selected_site_id:
            if os.path.exists(SITE_LIST_FILE):
                try:
                    site_list_df = pd.read_csv(SITE_LIST_FILE)
                    site_info = site_list_df[site_list_df['Site ID'] == selected_site_id]
    
                    if site_info.empty:
                        messagebox.showerror("Error", "No site information found for the selected Site ID.")
                        return
                    
                    parameters = set()
                    for _, row in site_info.iterrows():
                        site_name = row['File Name']
                        site_file_path = os.path.join(SITE_FILES_FOLDER, f"{site_name}")
    
                        if os.path.exists(site_file_path):
                            try:
                                site_data = pd.read_csv( site_file_path)
                                unnamed_columns = [col for col in site_data.columns if col.startswith('Unnamed:')]
                                site_data = site_data.drop(columns=unnamed_columns, axis=1)
                                if not site_data.empty:
                                    parameters.update(site_data.columns.tolist())
                                else:
                                    messagebox.showwarning("Warning", f"The site file {site_name} is empty or invalid.")
                            except pd.errors.ParserError as e:
                                messagebox.showwarning("Warning", f"Failed to read the site file {site_name}: {e}")
                            except Exception as e:
                                messagebox.showwarning("Warning", f"An unexpected error occurred while reading {site_name}: {e}")
                        else:
                            messagebox.showwarning("Warning", f"Site file {site_name} does not exist.")
    
                    if parameters:
                        parameter_combobox['values'] = list(parameters)
                    else:
                        messagebox.showerror("Error", "No valid data found in the site files.")
                except Exception as e:
                    messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            else:
                messagebox.showerror("Error", f"Site list file {SITE_LIST_FILE} does not exist.")
        else:
            messagebox.showerror("Error", "No Site ID selected.")

    site_id_combobox.bind("<<ComboboxSelected>>", update_parameters)
    
    # Function to plot the graph
    def plot_graph():
        selected_site_id = site_id_combobox.get()
        selected_parameter = parameter_combobox.get()
    
        if selected_site_id and selected_parameter:
            fig, ax = plt.subplots(figsize=(8, 5))
    
            if os.path.exists(SITE_LIST_FILE):
                try:
                    site_list_df = pd.read_csv(SITE_LIST_FILE)
                    site_info = site_list_df[site_list_df['Site ID'] == selected_site_id]
    
                    if site_info.empty:
                        messagebox.showerror("Error", "No site information found for the selected Site ID.")
                        return
                    
                    lines = []
                    line_properties = []
                    for _, row in site_info.iterrows():
                        site_name = row['File Name']
                        site_file_path = os.path.join(SITE_FILES_FOLDER, f"{site_name}")
    
                        if os.path.exists(site_file_path):
                            try:
                                site_data = pd.read_csv(site_file_path)
                                if 'local_time' in site_data.columns and selected_parameter in site_data.columns:
                                    site_data['local_time'] = site_data['local_time'].apply(parse_date)
                                    filtered_data = site_data
                                    line, = ax.plot(filtered_data['local_time'], filtered_data[selected_parameter], 
                                                    label=site_name)
                                    lines.append(line)
                                    line_properties.append({
                                        'color': line.get_color(),
                                        'linewidth': line.get_linewidth(),
                                        'alpha': line.get_alpha() if line.get_alpha() is not None else 1.0
                                    })
                                else:
                                    messagebox.showwarning("Warning", f"The file {site_name} does not contain the required columns.")
                            except pd.errors.ParserError as e:
                                messagebox.showwarning("Warning", f"Failed to read the site file {site_name}: {e}")
                            except Exception as e:
                                messagebox.showwarning("Warning", f"An unexpected error occurred while reading {site_name}: {e}")
                        else:
                            messagebox.showwarning("Warning", f"Site file {site_name} does not exist.")
                    
                    ax.set_title(f'{selected_parameter} over time for {selected_site_id}')
                    ax.set_xlabel('Local Time')
                    ax.set_ylabel('drips $hr^{-1}$' if selected_parameter == 'drip_rate' else selected_parameter)
                    ax.legend()
    
                    fig.autofmt_xdate()
    
                    # Add the figure to the Tkinter canvas
                    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
                    canvas.draw()
                    canvas.get_tk_widget().grid(row=2, column=0, columnspan=2, sticky='nsew')
    
                    # Add the navigation toolbar
                    toolbar_frame = ctk.CTkFrame(plot_frame)
                    toolbar_frame.grid(row=3, column=0, columnspan=2, sticky='nsew')
                    toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
                    toolbar.update()
    
                    # Make the plot interactive with hover highlighting and tooltips
                    cursor = mplcursors.cursor(lines, hover=mplcursors.HoverMode.Transient)
    
                    def on_hover(event):
                        hovered_line = None
                        for line in lines:
                            if line.contains(event)[0]:
                                hovered_line = line
                                break
    
                        if hovered_line:
                            for i, line in enumerate(lines):
                                if line == hovered_line:
                                    line.set_linewidth(2)
                                    line.set_alpha(1.0)
                                else:
                                    line.set_alpha(0.3)
                        else:
                            for i, line in enumerate(lines):
                                line.set_alpha(line_properties[i]['alpha'])
    
                        fig.canvas.draw_idle()
    
                    def on_leave(event):
                        for i, line in enumerate(lines):
                            line.set_alpha(line_properties[i]['alpha'])
                        fig.canvas.draw_idle()
    
                    fig.canvas.mpl_connect('motion_notify_event', on_hover)
                    fig.canvas.mpl_connect('figure_leave_event', on_leave)
    
                    @cursor.connect("add")
                    def on_add(sel):
                        x, y = sel.target
                        sel.annotation.set_text(f'{sel.artist.get_label()}\n{sel.target[1]:.2f}')
                        sel.annotation.get_bbox_patch().set(fc="yellow", alpha=0.6)
    
                except Exception as e:
                    messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            else:
                messagebox.showerror("Error", f"Site list file {SITE_LIST_FILE} does not exist.")
        else:
            messagebox.showerror("Error", "Please select both a Site ID and a parameter to plot.")
    
    plot_button = ctk.CTkButton(graph_frame, text="Plot Graph", command=plot_graph)
    plot_button.grid(row=1, column=2, padx=10, pady=10)
  
def open_pdf_file():
    operating_system = platform.system()
    file_path = os.path.join( "backend_datasets", 'Docs.pdf')
    # Open the file with the default application
    if operating_system == 'Windows':
        os.startfile(file_path)
    elif operating_system == 'Darwin':  # macOS
        os.system(f'open "{file_path}"')
    else:  # Linux and other Unix-like systems
        os.system(f'xdg-open "{file_path}"')

# Create the main window
root = ctk.CTk()
root.title("NGROS Database Management System")

# Calculate the screen width and height
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()

# Set window width and height
window_width = 850
window_height = 700

# Calculate x and y coordinates for centering the window
x_position = int((screen_width - window_width) / 2)
y_position = int((screen_height - window_height) / 2)
root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

# Configure grid for the main window
root.columnconfigure(1, weight=2)
root.rowconfigure(0, weight=1)

database_frame = ctk.CTkFrame(root)
database_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

out_frame = ctk.CTkFrame(root)
out_frame.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=5, pady=5)

input_frame = ctk.CTkFrame(database_frame)
input_frame.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

info_frame = ctk.CTkFrame(database_frame)
info_frame.grid(row=2, column=0, sticky='nsew', padx=5, pady=5)

out_text = scrolledtext.ScrolledText(out_frame, height=10, width=50)
out_text.pack(padx=5, pady=5, expand=True, fill="both")
scrolledtext_font = tkfont.Font(family="Calibri", size=13)  # Example font family and size
out_text.configure(font=scrolledtext_font)

display_frame = ctk.CTkFrame(root)
display_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)

info_label = ctk.CTkLabel(info_frame, text='Hello World', anchor="nw", font=('Calibri', 13))
info_label.pack(padx=5, pady=5, expand=True, fill="both")

# Create the label with the clickable shortcut
clickable_label = ctk.CTkLabel(info_frame, text="Parameter Document", anchor="nw", 
                               font=('Calibri', 13), cursor="hand2", text_color=("blue", "yellow"))
clickable_label.pack(padx=5, pady=5, expand=True, fill="both")

clickable_label.bind("<Button-1>", lambda event: open_pdf_file())

# Add button to input file or folder
add_site_button = ctk.CTkButton(input_frame, text="Upload New Site", command=add_site)
add_site_button.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

export_site_button = ctk.CTkButton(input_frame, text="Export Database", command=export_site)
export_site_button.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)

# Add combo box for display option selection
extent_label = ctk.CTkLabel(input_frame, text="Show Sites as:")
extent_label.grid(row=1, column=0, sticky='nsew', padx=5, pady=10)

display_options = ["Table", "Map"]
display_var = ctk.StringVar()
display_combobox = ctk.CTkComboBox(input_frame, values=display_options, variable=display_var)
display_combobox.set("Select an option")
display_combobox.grid(row=1, column=1, sticky='nsew', padx=5, pady=10)
display_var.trace("w", lambda *args: on_combobox_select())

separator = ttk.Separator(input_frame, orient=tk.HORIZONTAL)
separator.grid(row=2, column=0, columnspan=2, padx=5, pady=10, sticky='ew')

# Combobox to select file
file_label = ctk.CTkLabel(input_frame, text="Select Site File for Updation:")
file_label.grid(row=4, column=0, sticky='nsew', padx=5, pady=10)

selected_file = ctk.StringVar()
combobox = ctk.CTkComboBox(input_frame, variable=selected_file, state="readonly")
combobox.grid(row=4, column=1, sticky='nsew', padx=5, pady=10)

# Populate combobox with site files
site_files = [f for f in os.listdir(SITE_FILES_FOLDER) if f.endswith('.csv')]
combobox.configure(values = site_files)

# Button to fetch and update data
meteo_button = ctk.CTkButton(input_frame, text="Fetch Meteorological Data", 
                              command=lambda: on_update(selected_file.get(), input_frame))
meteo_button.grid(row=5, column = 0, sticky='nsew', padx=5, pady=5)

topo_button = ctk.CTkButton(input_frame, text="Fetch Topographical Data", state = 'disabled')
topo_button.grid(row=5, column = 1, sticky='nsew', padx=5, pady=5)

check_var = ctk.StringVar()
def checkbox_event():
    if check_var.get() == 'on':
        site_files = [f for f in os.listdir(SITE_FILES_FOLDER) if f.endswith('.csv')]
        combobox.configure(values = site_files)

checkbox = ctk.CTkCheckBox(master=input_frame, text="Refresh Sites", command=checkbox_event, checkbox_height = 18, checkbox_width = 18,
                                     variable=check_var, onvalue="on", offvalue="off")
checkbox.grid(row=3, column = 0, sticky='nsew', padx=5, pady=5)
checkbox.select()

# Ensure that widgets take the full space of the frames
database_frame.grid_rowconfigure(1, weight=1)
database_frame.grid_rowconfigure(2, weight=1)
database_frame.grid_columnconfigure(0, weight=1)
out_frame.grid_rowconfigure(0, weight=1)
display_frame.grid_rowconfigure(0, weight=1)
display_frame.grid_columnconfigure(0, weight=1)

# Load site list on startup
load_site_list()
plt.ioff()
plt.close()
root.mainloop()
