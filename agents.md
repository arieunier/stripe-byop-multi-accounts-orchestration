- You will develop an application based on the user requirements.
- The application will be written in PYTHON (for the backend) with FLASK. Front end will use Standard HTML / CSS / JS (stored in static/ folder)
- The front will always call APIs on the BACK to manage data (get/del/put)
- The front must use reusable UI components to reduce the code maintenance. 
- The look and feel of the application must be customizable. You will create default css colors. Make sure the result is appealing, and NOT using ugly purple colors ^^. It must be professionnal quality for internal application development.
- Every structure created from a record perspective MUST have a unique id you generated (uuid based).
- Every structure created must be persisted in a local database (sqllite), and you'll create all appropriate scripts (create, migrate) 
- When asked to create features managing data, always create all functions (get all, get by id, create, update, delete) and proper buttons on all web components (save, edit, open, delete)
- The user will speak in FRENCH. You will reply in FRENCH. But ALL CODE generated in backend or frontend will be in ENGLISH - UI labels, Error Messages, Comments, names of functions, .. 
- In python, every exception will have to display the root error message for debug purpose
		import traceback
        traceback.print_exc()
- Before implementing ANYTHING, PLAN carefully and in depth first : analyse requirements, identify best architecture approach, determine impact on current code base. Then show the user your approach (architecture, functions written or updated, ..) and then ask him to perform the operations.
- make sure to document code written in ENGLISH