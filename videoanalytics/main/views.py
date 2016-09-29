import csv

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import logout as auth_logout_view
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.http.response import HttpResponseRedirect, StreamingHttpResponse
from django.views.generic.base import TemplateView, View
from djangowind.views import logout as wind_logout_view
from pagetree.generic.views import EditView, PageView
from pagetree.models import Hierarchy
from pagetree.models import PageBlock
from quizblock.models import Quiz, Submission

from videoanalytics.main.mixins import JSONResponseMixin, LoggedInMixin, \
    LoggedInSuperuserMixin, LoggedInStaffMixin
from videoanalytics.main.models import VideoAnalyticsReport, UserVideoView


def context_processor(request):
    ctx = {}
    ctx['site'] = Site.objects.get_current()
    ctx['MEDIA_URL'] = settings.MEDIA_URL
    return ctx


def get_quiz_blocks(css_class):
    quiz_type = ContentType.objects.get_for_model(Quiz)
    blocks = PageBlock.objects.filter(css_extra=css_class,
                                      content_type=quiz_type)
    return blocks


class LoginView(JSONResponseMixin, View):

    def post(self, request):
        request.session.set_test_cookie()
        login_form = AuthenticationForm(request, request.POST)
        if login_form.is_valid():
            login(request, login_form.get_user())
            if request.user is not None:
                next_url = request.POST.get('next', '/')
                return self.render_to_json_response({'next': next_url})
        else:
            return self.render_to_json_response({'error': True})


class LogoutView(LoggedInMixin, View):

    def get(self, request):
        if request.user.profile.is_participant():
            url = request.user.profile.last_location_url()
            return HttpResponseRedirect(url)
        elif hasattr(settings, 'WIND_BASE'):
            return wind_logout_view(request, next_page="/")
        else:
            return auth_logout_view(request, "/")


class RestrictedEditView(LoggedInSuperuserMixin, EditView):
    template_name = "pagetree/edit_page.html"


class RestrictedPageView(PageView):

    def perform_checks(self, request, path):
        user = self.request.user
        section = self.get_section(path)

        if (not user.is_superuser and
                section.hierarchy.name != user.profile.research_group):
            return HttpResponseRedirect(user.profile.last_location_url())

        return super(RestrictedPageView, self).perform_checks(request, path)


class VideoPageView(PageView):

    def perform_checks(self, request, path):
        user = self.request.user
        section = self.get_section(path)

        # users in the diagnostic hierarchy must have submissions
        if (section.hierarchy.name == 'videos' and
            not user.profile.in_control_group() and
                not Submission.objects.filter(user=user).exists()):
            return HttpResponseRedirect(user.profile.last_location_url())

        return super(VideoPageView, self).perform_checks(request, path)


class IndexView(TemplateView):
    template_name = 'main/splash.html'

    def dispatch(self, *args, **kwargs):
        user = self.request.user
        if not user.is_anonymous():
            return HttpResponseRedirect(user.profile.last_location_url())

        return super(IndexView, self).dispatch(*args, **kwargs)


class TrackVideoView(LoggedInMixin, JSONResponseMixin, View):

    def post(self, request):
        vid = request.POST.get('video_id', '')
        video_duration = int(request.POST.get('video_duration', 0))
        seconds_viewed = int(request.POST.get('seconds_viewed', 0))

        if vid == '':
            context = {'success': False, 'msg': 'Invalid video id'}
        elif video_duration < 1:
            context = {'success': False, 'msg': 'Invalid video duration'}
        else:
            uvv = UserVideoView.objects.get_or_create(user=request.user,
                                                      video_id=vid)
            uvv[0].video_duration = video_duration
            uvv[0].seconds_viewed += seconds_viewed
            uvv[0].save()

            context = {'success': True}

        return self.render_to_json_response(context)


class Echo(object):
    """An object that implements just the write method of the file-like
    interface.
    """
    def write(self, value):
        """Write the value by returning it, instead of storing in a buffer."""
        return value


class ReportView(LoggedInStaffMixin, View):

    def get(self, request):
        report = VideoAnalyticsReport()
        hierarchies = Hierarchy.objects.all()

        report_type = request.GET.get('type', 'key')
        if report_type == 'values':
            rows = report.values(hierarchies)
        else:
            rows = report.metadata(hierarchies)

        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)

        fnm = "videoanalytics_%s.csv" % report_type
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in rows), content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename="' + fnm + '"'
        return response
