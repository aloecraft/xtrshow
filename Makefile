ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
__TECHNO_PROJECT_FILE:=${ROOT_DIR}/.technoproj

-include ${ROOT_DIR}/script/version.mk
-include ${ROOT_DIR}/script/python.mk

echo:
	@echo VERSION: ${__VERSION_FULL}
	@echo TAG: ${__TAG}

clean:

	rm -rf dist/ build/ *.egg-info .ruff_cache .pytest_cache .html_doc __pycache__

# Builds locally; it does not publish. Releases go out only by pushing a
# tag, which runs the suite first and keeps -dev.N tags off PyPI. There is
# no upload target on purpose: a manual twine upload walks around both of
# those gates. 0.1.0 and 0.2.0 sit on PyPI today with no tag behind them,
# which is what that looks like afterwards. See doc/ALIGNMENT.md, 7 and 9.
build:

	python3 -m build

docgen:
	mkdir -p .html_doc
	pandoc README.md -o .html_doc/readme.html -f markdown+emoji
	python3 script/pydocgen.py xtrshow/ .html_doc --title "xtrshow" --readme .html_doc/readme.html
	(cd .html_doc && python3 -m http.server)